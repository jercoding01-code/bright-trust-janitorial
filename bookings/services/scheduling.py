from datetime import datetime, time, timedelta
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from bookings.models import CleaningLead

def get_scheduling_config():
    """
    Get scheduling configuration values from settings, with fallbacks.
    """
    return {
        'SERVICE_DURATION_HOURS': getattr(settings, 'SERVICE_DURATION_HOURS', 4),
        'BOOKING_SLOT_INTERVAL_MINUTES': getattr(settings, 'BOOKING_SLOT_INTERVAL_MINUTES', 60),
        'MAX_CONCURRENT_CREWS': getattr(settings, 'MAX_CONCURRENT_CREWS', 1),
    }

def get_available_slots_for_date(selected_date):
    """
    Generates a list of available HH:MM strings for a given date object.
    Matches operational rule: 24/7 coverage.
    """
    config = get_scheduling_config()
    default_duration = config['SERVICE_DURATION_HOURS']
    interval_mins = config['BOOKING_SLOT_INTERVAL_MINUTES']
    max_crews = config['MAX_CONCURRENT_CREWS']
    
    tz = timezone.get_current_timezone()
    start_of_day = timezone.make_aware(datetime.combine(selected_date, time.min), tz)
    end_of_day = timezone.make_aware(datetime.combine(selected_date, time.max), tz)
    
    # Query active bookings that could overlap with any time on the selected date.
    active_statuses = ['SCHEDULED']
    
    from django.db.models import Q
    existing_bookings = CleaningLead.objects.filter(
        status__in=active_statuses,
        requested_date_time__lt=end_of_day
    ).filter(
        Q(requested_end_time__gt=start_of_day) | Q(requested_end_time__isnull=True)
    )
    
    available_slots = []
    
    # Generate slots for the full 24 hours in intervals
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

def check_and_reserve_slot(lead):
    """
    Validates availability of a slot for a specific booking lead.
    Utilizes select_for_update() to prevent race conditions on query phase.
    """
    config = get_scheduling_config()
    duration_hours = lead.service_duration_hours or config['SERVICE_DURATION_HOURS']
    max_crews = config['MAX_CONCURRENT_CREWS']
    
    if not lead.requested_date_time:
        return False
        
    slot_start = lead.requested_date_time
    slot_end = slot_start + timedelta(hours=duration_hours)
    
    lead.requested_end_time = slot_end
    
    active_statuses = ['SCHEDULED']
    
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
                    # Specific assigned cleaner already has a scheduled job during this time!
                    return False
                
        if overlapping_count >= max_crews:
            return False
            
        lead.save()
        return True


def schedule_admin_booking(lead, user=None, is_new=False, request_context=None):
    """
    Centralized service function for administrator booking scheduling.
    Wraps DB mutations (slot reservation, payment status initialization, audit logging) in transaction.atomic().
    Registers safe post-commit email dispatch via transaction.on_commit().
    Returns (success: bool, error_message: str or None).
    """
    import logging
    logger = logging.getLogger(__name__)
    from decimal import Decimal
    from bookings.services.audit import log_financial_event
    from bookings.models import BusinessSettings
    
    old_status = getattr(lead, '_old_status', None) if not is_new else None
    
    with transaction.atomic():
        # 1. Lock calendar slot concurrency only if status is SCHEDULED
        if lead.status == 'SCHEDULED':
            if not check_and_reserve_slot(lead):
                return False, "This time slot conflicts with an existing active booking."
        else:
            lead.save()
            
        # 2. Ensure status is SCHEDULED and payment_status is PENDING if unassigned
        if lead.status == 'SCHEDULED' and not lead.payment_status:
            lead.payment_status = 'PENDING'
            
        lead.save()
        
        # 3. Audit logging inside transaction
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
            
        # 4. Register safe email dispatch post-commit via transaction.on_commit
        if lead.status == 'SCHEDULED' and lead.email:
            def dispatch_confirmation_email():
                try:
                    price = lead.final_quote_price if (lead.final_quote_price and lead.final_quote_price > 0) else (lead.system_estimated_price if lead.system_estimated_price else Decimal('0.00'))
                    formatted_price = f"${price:,.2f}"
                    formatted_date_time = lead.requested_date_time.strftime('%b %d, %Y, %I:%M %p') if lead.requested_date_time else 'Scheduled Time'
                    doc_type = "Booking Confirmation & Quote"
                    intro = "Your cleaning appointment has been scheduled by our staff! Please review your service details and submit your deposit below:"
                    
                    # 1. Use lead's own dynamic Square Checkout URL if available
                    payment_link = lead.square_checkout_url
                    if not payment_link:
                        # 2. Automatically generate dynamic Square Checkout link via Square API using developer credentials
                        from bookings.views import create_square_checkout_link
                        payment_link = create_square_checkout_link(lead)
                    if not payment_link:
                        # 3. Fallback to BusinessSettings or SQUARE_PAYMENT_LINK env var
                        biz_settings = BusinessSettings.objects.first()
                        payment_link = (biz_settings.square_payment_link if (biz_settings and biz_settings.square_payment_link) else None) or getattr(django_settings, 'SQUARE_PAYMENT_LINK', None)
                    
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
                        
                    from django.conf import settings as django_settings
                    from bookings.views import send_email_via_resend_api
                    if getattr(django_settings, 'EMAIL_HOST_USER', None):
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

