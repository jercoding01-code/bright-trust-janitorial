import logging
from django.utils import timezone
from django.db import transaction
from bookings.models import CleanerProfile, CleaningLead
from bookings.services.audit import log_financial_event

logger = logging.getLogger(__name__)

def authenticate_cleaner(phone, raw_pin):
    """
    Authenticates a cleaner via phone number and raw PIN.
    Updates last_login_at on success.
    Logs CLEANER_LOGIN_FAILED on authentication failure.
    Returns (cleaner_profile: CleanerProfile or None, error_message: str or None)
    """
    import re
    digits_only = re.sub(r'\D', '', str(phone or ''))
    if len(digits_only) == 11 and digits_only.startswith('1'):
        digits_only = digits_only[1:]
        
    try:
        cleaner = CleanerProfile.objects.get(phone=digits_only)
    except CleanerProfile.DoesNotExist:
        try:
            cleaner = CleanerProfile.objects.get(phone=phone)
        except CleanerProfile.DoesNotExist:
            logger.warning(f"CLEANER_LOGIN_FAILED: Phone {phone} not found.")
            return None, "Invalid phone number or PIN. Please try again."
            
    if not cleaner.is_active:
        logger.warning(f"CLEANER_LOGIN_FAILED: Account for {cleaner.name} ({cleaner.phone}) is inactive.")
        return None, "Your cleaner account is currently inactive. Please contact management."
        
    if not cleaner.check_pin(raw_pin):
        logger.warning(f"CLEANER_LOGIN_FAILED: Invalid PIN attempt for {cleaner.name} ({cleaner.phone}).")
        return None, "Invalid phone number or PIN. Please try again."
        
    cleaner.last_login_at = timezone.now()
    cleaner.save(update_fields=['last_login_at'])
    return cleaner, None


def assign_cleaner_to_lead(lead, cleaner, user=None):
    """
    Assigns a cleaner to a booking lead, logging ASSIGNED_CLEANER_CHANGED audit entry,
    and dispatching an email notification if cleaner.email is set.
    """
    old_cleaner_name = lead.assigned_cleaner.name if lead.assigned_cleaner else "Unassigned"
    new_cleaner_name = cleaner.name if cleaner else "Unassigned"
    
    if lead.assigned_cleaner != cleaner:
        lead.assigned_cleaner = cleaner
        lead.save(update_fields=['assigned_cleaner'])
        
        log_financial_event(
            booking=lead,
            action='ASSIGNED_CLEANER_CHANGED',
            field_name='assigned_cleaner',
            old_value=old_cleaner_name,
            new_value=new_cleaner_name,
            changed_by=user,
            source='USER',
            notes=f"Assigned cleaner changed from {old_cleaner_name} to {new_cleaner_name}."
        )
        
        # Dispatch cleaner notification email if cleaner is set and has an email
        if cleaner and cleaner.email:
            def dispatch_cleaner_alert():
                try:
                    from bookings.views import send_email_via_resend_api
                    from django.conf import settings as django_settings
                    
                    date_str = lead.requested_date_time.strftime('%b %d, %Y, %I:%M %p') if lead.requested_date_time else 'Scheduled Time'
                    subject = f"New Job Assignment: {lead.first_name} {lead.last_name} ({date_str})"
                    
                    text_content = (
                        f"BRIGHT TRUST JANITORIAL - JOB ASSIGNMENT\n\n"
                        f"Hi {cleaner.name},\n\n"
                        f"You have been assigned to a cleaning job!\n\n"
                        f"Client: {lead.first_name} {lead.last_name}\n"
                        f"Date & Time: {date_str}\n"
                        f"Address: {lead.address}\n"
                        f"Service Type: {lead.get_service_type_display()}\n\n"
                        f"Log in to your portal to view full instructions: https://brighttrustjanitorial.ca/cleaner/\n"
                    )
                    
                    if getattr(django_settings, 'EMAIL_HOST_USER', None):
                        send_email_via_resend_api(subject, text_content, text_content, cleaner.email)
                except Exception as e:
                    logger.error(f"Failed to send cleaner assignment notification to {cleaner.email}: {e}")
                    
            transaction.on_commit(dispatch_cleaner_alert)


def get_assigned_jobs_for_cleaner(cleaner):
    """
    Returns active SCHEDULED jobs assigned to a cleaner.
    """
    if not cleaner or not cleaner.pk:
        return CleaningLead.objects.none()
    return CleaningLead.objects.filter(
        assigned_cleaner=cleaner,
        status='SCHEDULED'
    ).select_related('assigned_cleaner').order_by('requested_date_time')
