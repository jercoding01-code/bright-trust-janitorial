"""
bookings/services/cleaners.py

Cleaner Staff Subsystem & 2FA Authentication Service.

Cleaner Authentication Flow
---------------------------
Phone Number + 6-Digit PIN Entry
        ↓
Phone Normalization & Cleaner Lookup
        ↓
PBKDF2 Hashed PIN Verification (check_password)
        ↓
Session Creation & 30-Day Expiry (CLEANER_SESSION_AGE)
        ↓
Assigned Job Dashboard & Privacy Shield

Responsibilities
----------------
- Authenticate cleaner staff via Phone Number + 6-Digit PIN.
- Normalize Canadian 10-digit phone inputs.
- Maintain PBKDF2 encrypted PIN validation (never storing plain-text keys).
- Assign cleaner profiles to bookings and generate ASSIGNED_CLEANER_CHANGED audit events.
- Dispatch automated email alerts to cleaner staff upon new job assignment.
- Filter active SCHEDULED jobs for personalized cleaner portal views.

Security Notes
--------------
• Cleaner PINs are hashed using Django's standard PBKDF2 PasswordHasher.
• Failed login attempts are logged as CLEANER_LOGIN_FAILED warnings for security monitoring.
"""

import logging
import re
from typing import Optional, Tuple, TYPE_CHECKING
from django.utils import timezone
from django.db import transaction
from django.db.models import QuerySet
from bookings.models import CleanerProfile, CleaningLead
from bookings.services.audit import log_financial_event

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def authenticate_cleaner(
    phone: str,
    raw_pin: str
) -> Tuple[Optional[CleanerProfile], Optional[str]]:
    """Authenticates a cleaner staff member via phone number and raw numeric PIN.

    Args:
        phone (str): The raw phone number input by the cleaner.
        raw_pin (str): The unhashed 6-digit PIN entered on the login form.

    Returns:
        Tuple[Optional[CleanerProfile], Optional[str]]: (cleaner_instance, error_message).
            Returns (CleanerProfile, None) on success; (None, error_str) on failure.

    Note:
        SECURITY & AUDIT:
        - Normalizes 10-digit North American phone numbers (stripping country code +1 or symbols).
        - Verifies that cleaner.is_active is True.
        - Uses cleaner.check_pin(raw_pin) to perform PBKDF2 hash verification.
        - Updates last_login_at timestamp on successful authentication.
        - Logs CLEANER_LOGIN_FAILED warnings for invalid phone numbers or incorrect PIN attempts.
    """
    digits_only: str = re.sub(r'\D', '', str(phone or ''))
    if len(digits_only) == 11 and digits_only.startswith('1'):
        digits_only = digits_only[1:]
        
    try:
        cleaner: CleanerProfile = CleanerProfile.objects.get(phone=digits_only)
    except CleanerProfile.DoesNotExist:
        try:
            cleaner = CleanerProfile.objects.get(phone=phone)
        except CleanerProfile.DoesNotExist:
            logger.warning(f"CLEANER_LOGIN_FAILED: Phone number '{phone}' not found in cleaner directory.")
            return None, "Invalid phone number or PIN. Please try again."
            
    if not cleaner.is_active:
        logger.warning(f"CLEANER_LOGIN_FAILED: Account for {cleaner.name} ({cleaner.phone}) is marked inactive/terminated.")
        return None, "Your cleaner account is currently inactive. Please contact management."
        
    if not cleaner.check_pin(raw_pin):
        logger.warning(f"CLEANER_LOGIN_FAILED: Invalid PIN authentication attempt for {cleaner.name} ({cleaner.phone}).")
        return None, "Invalid phone number or PIN. Please try again."
        
    cleaner.last_login_at = timezone.now()
    cleaner.save(update_fields=['last_login_at'])
    return cleaner, None


def assign_cleaner_to_lead(
    lead: CleaningLead,
    cleaner: Optional[CleanerProfile],
    user: Optional['User'] = None
) -> None:
    """Assigns or reassigns a cleaner to a booking lead, logging audit history and sending email alerts.

    Args:
        lead (CleaningLead): The target booking lead instance.
        cleaner (Optional[CleanerProfile]): The cleaner profile to assign, or None to unassign.
        user (Optional[User]): The administrative user initiating assignment.

    Note:
        AUDIT & NOTIFICATION:
        - Records ASSIGNED_CLEANER_CHANGED in FinancialAuditLog (e.g. 'Sarah Connor' -> 'Bob Builder').
        - Dispatches an automated job assignment email notification to cleaner.email post-commit.
    """
    old_cleaner_name: str = lead.assigned_cleaner.name if lead.assigned_cleaner else "Unassigned"
    new_cleaner_name: str = cleaner.name if cleaner else "Unassigned"
    
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
        
        # Dispatch cleaner notification email if cleaner is assigned and has an email address
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


def get_assigned_jobs_for_cleaner(
    cleaner: Optional[CleanerProfile]
) -> QuerySet[CleaningLead]:
    """Retrieves active SCHEDULED jobs assigned to a specific cleaner staff member.

    Args:
        cleaner (Optional[CleanerProfile]): The cleaner profile instance to query jobs for.

    Returns:
        QuerySet[CleaningLead]: QuerySet of active CleaningLead instances ordered by date/time.
    """
    if not cleaner or not cleaner.pk:
        return CleaningLead.objects.none()
    return CleaningLead.objects.filter(
        assigned_cleaner=cleaner,
        status='SCHEDULED'
    ).select_related('assigned_cleaner').order_by('requested_date_time')
