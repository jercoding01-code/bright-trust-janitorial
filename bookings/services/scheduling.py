"""
bookings/services/scheduling.py

Janitorial Booking Scheduling & Concurrency Control Service.

Responsibilities
----------------
- Calculate 4-hour time slot availability across 24/7 calendar days.
- Enforce total company crew capacity limits (MAX_CONCURRENT_CREWS).
- Enforce per-cleaner schedule conflict checking (preventing double-booking specific staff).
- Provide atomic transaction boundaries for administrative booking creation and status overrides.
- Register safe post-commit email dispatches (transaction.on_commit) for scheduled jobs.

Architecture & Concurrency Notes
--------------------------------
• Scheduling conflicts are prevented at the database query phase via select_for_update() row-locking.
• Email dispatches are deferred via transaction.on_commit() to ensure that confirmation emails
  are ONLY sent after the database transaction successfully commits. If a database error or slot conflict
  rolls back the transaction, no phantom emails are sent to clients.
"""

import logging
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest
from bookings.models import CleaningLead, BusinessSettings
from bookings.services.audit import log_financial_event

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def get_scheduling_config() -> Dict[str, Any]:
    """Retrieves operational scheduling parameters from Django settings with safe fallbacks.

    Returns:
        Dict[str, Any]: Dictionary containing SERVICE_DURATION_HOURS,
            BOOKING_SLOT_INTERVAL_MINUTES, and MAX_CONCURRENT_CREWS.
    """
    return {
        'SERVICE_DURATION_HOURS': getattr(settings, 'SERVICE_DURATION_HOURS', 4),
        'BOOKING_SLOT_INTERVAL_MINUTES': getattr(settings, 'BOOKING_SLOT_INTERVAL_MINUTES', 60),
        'MAX_CONCURRENT_CREWS': getattr(settings, 'MAX_CONCURRENT_CREWS', 1),
    }


def get_available_slots_for_date(selected_date: date) -> List[str]:
    """Generates available start time strings (HH:MM) for a target calendar date.

    Args:
        selected_date (date): The target date object to calculate slot availability for.

    Returns:
        List[str]: List of 24-hour time strings (e.g., ['09:00', '13:00', '17:00']) with open capacity.

    Note:
        A slot is considered available if total overlapping SCHEDULED bookings on that date
        are strictly less than MAX_CONCURRENT_CREWS.
    """
    config: Dict[str, Any] = get_scheduling_config()
    default_duration: int = config['SERVICE_DURATION_HOURS']
    interval_mins: int = config['BOOKING_SLOT_INTERVAL_MINUTES']
    max_crews: int = config['MAX_CONCURRENT_CREWS']
    
    tz = timezone.get_current_timezone()
    start_of_day = timezone.make_aware(datetime.combine(selected_date, time.min), tz)
    end_of_day = timezone.make_aware(datetime.combine(selected_date, time.max), tz)
    
    active_statuses = ['SCHEDULED']
    
    from django.db.models import Q
    existing_bookings = CleaningLead.objects.filter(
        status__in=active_statuses,
        requested_date_time__lt=end_of_day
    ).filter(
        Q(requested_end_time__gt=start_of_day) | Q(requested_end_time__isnull=True)
    )
    
    available_slots: List[str] = []
    
    current_time = start_of_day
    while current_time < end_of_day:
        slot_start = current_time
        slot_end = current_time + timedelta(hours=default_duration)
        
        overlapping_count = 0
        for booking in existing_bookings:
            eb_start = booking.requested_date_time
            eb_end = booking.requested_end_time or (eb_start + timedelta(hours=default_duration))
            
            if slot_start < eb_end and slot_end > eb_start:
                overlapping_count += 1
                
        if overlapping_count < max_crews:
            available_slots.append(slot_start.strftime('%H:%M'))
            
        current_time += timedelta(minutes=interval_mins)
        
    return available_slots


def check_and_reserve_slot(lead: CleaningLead) -> bool:
    """Validates slot availability and reserves calendar capacity under a database lock.

    Args:
        lead (CleaningLead): The booking lead containing requested_date_time and optional assigned_cleaner.

    Returns:
        bool: True if slot is successfully validated and reserved; False if a conflict exists.

    Note:
        CONCURRENCY & PER-CLEANER CHECKS:
        1. Utilizes select_for_update() row locking to prevent race conditions during query checks.
        2. Checks total company crew capacity against MAX_CONCURRENT_CREWS.
        3. If assigned_cleaner is set, verifies that the cleaner does not already have an overlapping booking.
    """
    config: Dict[str, Any] = get_scheduling_config()
    duration_hours: int = lead.service_duration_hours or config['SERVICE_DURATION_HOURS']
    max_crews: int = config['MAX_CONCURRENT_CREWS']
    
    if not lead.requested_date_time:
        return False
        
    slot_start = lead.requested_date_time
    slot_end = slot_start + timedelta(hours=duration_hours)
    
    lead.requested_end_time = slot_end
    
    active_statuses = ['SCHEDULED']
    
    # Execute under atomic row lock to eliminate parallel booking race conditions
    with transaction.atomic():
        from django.db.models import Q
        existing_bookings = CleaningLead.objects.select_for_update().filter(
            status__in=active_statuses,
            requested_date_time__lt=slot_end
        ).filter(
            Q(requested_end_time__gt=slot_start) | Q(requested_end_time__isnull=True)
        )
        
        overlapping_count = 0
        for booking in existing_bookings:
            if lead.pk and booking.pk == lead.pk:
                continue
            
            eb_start = booking.requested_date_time
            eb_end = booking.requested_end_time or (eb_start + timedelta(hours=config['SERVICE_DURATION_HOURS']))
            
            if slot_start < eb_end and slot_end > eb_start:
                overlapping_count += 1
                if lead.assigned_cleaner_id and booking.assigned_cleaner_id == lead.assigned_cleaner_id:
                    # Specific assigned cleaner already has an overlapping scheduled job!
                    return False
                
        if overlapping_count >= max_crews:
            return False
            
        lead.save()
        return True


def schedule_admin_booking(
    lead: CleaningLead,
    user: Optional['User'] = None,
    is_new: bool = False,
    request_context: Optional[HttpRequest] = None
) -> Tuple[bool, Optional[str]]:
    """Centralized service method for administrative scheduling and phone booking creation.

    Args:
        lead (CleaningLead): The booking lead instance to schedule or update.
        user (Optional[User]): Administrative user performing the action.
        is_new (bool): True if creating a new manual booking; False if editing existing lead.
        request_context (Optional[HttpRequest]): Optional HTTP request for protocol/host header resolution.

    Returns:
        Tuple[bool, Optional[str]]: (success_status, error_message_or_none).

    Note:
        ATOMICITY & SAFE DISPATCH:
        DB mutations (slot reservation, payment status initialization, audit logging) are wrapped in
        transaction.atomic(). Confirmation email dispatch is deferred via transaction.on_commit().
    """
    old_status = getattr(lead, '_old_status', None) if not is_new else None
    
    with transaction.atomic():
        # 1. Validate and lock calendar slot concurrency if status is SCHEDULED
        if lead.status == 'SCHEDULED':
            if not check_and_reserve_slot(lead):
                return False, "This time slot conflicts with an existing active booking or assigned cleaner schedule."
        else:
            lead.save()
            
        # 2. Ensure payment status defaults to PENDING for new scheduled jobs
        if lead.status == 'SCHEDULED' and not lead.payment_status:
            lead.payment_status = 'PENDING'
            
        lead.save()
        
        # 3. Create immutable audit logs inside transaction boundary
        if is_new:
            log_financial_event(
                booking=lead,
                action='QUOTE_CREATED',
                changed_by=user,
                source='USER',
                notes="Booking created directly by administrator (phone/manual)."
            )
            log_financial_event(
                booking=lead,
                action='STATUS_CHANGED',
                field_name='status',
                old_value='NONE',
                new_value='SCHEDULED',
                changed_by=user,
                source='USER',
                notes="Initial status set to SCHEDULED by administrator."
            )
        else:
            log_financial_event(
                booking=lead,
                action='STATUS_CHANGED',
                field_name='status',
                old_value=old_status or 'NEW',
                new_value=lead.status,
                changed_by=user,
                source='USER',
                notes=f"Booking status updated from {old_status or 'NEW'} to {lead.status} by administrator."
            )
            
        # 4. Deferred post-commit email dispatch: triggers ONLY after DB transaction commits successfully
        if lead.status == 'SCHEDULED' and lead.email:
            def dispatch_confirmation_email():
                try:
                    price: Decimal = lead.final_quote_price if (lead.final_quote_price and lead.final_quote_price > 0) else (lead.system_estimated_price if lead.system_estimated_price else Decimal('0.00'))
                    formatted_price = f"${price:,.2f}"
                    formatted_date_time = lead.requested_date_time.strftime('%b %d, %Y, %I:%M %p') if lead.requested_date_time else 'Scheduled Time'
                    doc_type = "Booking Confirmation & Quote"
                    intro = "Your cleaning appointment has been scheduled by our staff! Please review your service details and submit your deposit below:"
                    
                    # 1. Use lead's custom Square Checkout URL if set
                    payment_link = lead.square_checkout_url
                    if not payment_link:
                        # 2. Automatically generate dynamic Square Checkout link via Square Developer API
                        from bookings.views import create_square_checkout_link
                        payment_link = create_square_checkout_link(lead)
                    if not payment_link:
                        # 3. Fallback to BusinessSettings or SQUARE_PAYMENT_LINK env var
                        biz_settings = BusinessSettings.objects.first()
                        payment_link = (biz_settings.square_payment_link if (biz_settings and biz_settings.square_payment_link) else None) or getattr(settings, 'SQUARE_PAYMENT_LINK', None)
                    
                    subject = f"Booking Confirmed: Cleaning Services - Bright Trust Janitorial"
                    
                    protocol = 'https'
                    host = 'brighttrustjanitorial.ca'
                    if request_context:
                        protocol = 'https' if request_context.is_secure() else 'http'
                        host = request_context.get_host()
                        
                    logo_url = f"{protocol}://{host}/static/images/logo.JPEG"
                    
                    from django.template.loader import render_to_string
                    context = {
                        'lead': lead,
                        'doc_type': doc_type,
                        'intro': intro,
                        'formatted_price': formatted_price,
                        'formatted_date_time': formatted_date_time,
                        'payment_link': payment_link,
                        'logo_url': logo_url,
                    }
                    html_content = render_to_string('email_quote.html', context)
                    text_content = (
                        f"BRIGHT TRUST JANITORIAL INC.\n"
                        f"Dear {lead.first_name} {lead.last_name},\n\n"
                        f"{intro}\n\n"
                        f"Service Date: {formatted_date_time}\n"
                        f"Total Quote: {formatted_price}\n"
                    )
                    if payment_link:
                        text_content += f"\nDeposit Link: {payment_link}\n"
                        
                    from bookings.views import send_email_via_resend_api
                    if getattr(settings, 'EMAIL_HOST_USER', None):
                        send_email_via_resend_api(subject, text_content, html_content, lead.email)
                except Exception as e:
                    logger.error(f"Failed to send admin confirmation email for booking {lead.pk}: {e}")
                    log_financial_event(
                        booking=lead,
                        action='EMAIL_FAILED',
                        changed_by=user,
                        source='SYSTEM',
                        notes=f"Admin scheduled email dispatch error: {str(e)}"
                    )
                    
            transaction.on_commit(dispatch_confirmation_email)
            
    return True, None
