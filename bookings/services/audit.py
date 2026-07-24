"""
bookings/services/audit.py

Financial Audit Logging & CRA Compliance Service.

Responsibilities
----------------
- Record immutable audit trail events for financial, status, and assignment changes.
- Deduplicate redundant state changes (preventing zero-op audit records).
- Format and store change metadata for Canadian Revenue Agency (CRA) tax compliance.

Architecture & Compliance Notes
--------------------------------
• Financial audit records are immutable. Once created, they provide permanent historical evidence
  for invoice creation, payment processing, price overrides, and cleaner assignments.
• This module contains no HTTP or UI logic.
"""

from typing import Any, Optional, TYPE_CHECKING
from bookings.models import FinancialAuditLog, CleaningLead

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def log_financial_event(
    booking: CleaningLead,
    action: str,
    field_name: Optional[str] = None,
    old_value: Any = None,
    new_value: Any = None,
    changed_by: Optional['User'] = None,
    source: str = 'SYSTEM',
    notes: Optional[str] = None
) -> Optional[FinancialAuditLog]:
    """Creates an immutable audit log record in FinancialAuditLog for a booking change.

    Args:
        booking (CleaningLead): The target booking lead instance being audited.
        action (str): Action category string (e.g. 'QUOTE_CREATED', 'STATUS_CHANGED', 'INVOICE_GENERATED').
        field_name (Optional[str]): Field name modified (e.g. 'status', 'assigned_cleaner').
        old_value (Any): Prior field state value before modification.
        new_value (Any): Updated field state value after modification.
        changed_by (Optional[User]): User initiating the change, or None for automated triggers.
        source (str): Change source identifier (e.g. 'USER', 'SYSTEM', 'SQUARE_WEBHOOK').
        notes (Optional[str]): Human-readable narrative detailing the change context.

    Returns:
        Optional[FinancialAuditLog]: The created FinancialAuditLog instance, or None if skipped as duplicate.

    Note:
        DEDUPLICATION SAFEGUARD:
        If old_value == new_value and neither is None, the function exits early to prevent redundant records.
    """
    # Safeguard: Do not log if old and new values are identical
    if old_value == new_value and old_value is not None:
        return None

    # Cast values to string to fit varchar database schema boundaries
    old_str: Optional[str] = str(old_value) if old_value is not None else None
    new_str: Optional[str] = str(new_value) if new_value is not None else None

    return FinancialAuditLog.objects.create(
        booking=booking,
        action=action,
        field_name=field_name,
        old_value=old_str,
        new_value=new_str,
        changed_by=changed_by,
        source=source,
        notes=notes
    )
