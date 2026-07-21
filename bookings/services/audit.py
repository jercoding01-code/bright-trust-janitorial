from bookings.models import FinancialAuditLog

def log_financial_event(booking, action, field_name=None, old_value=None, new_value=None, changed_by=None, source='SYSTEM', notes=None):
    """
    Explicitly logs a financial audit event to the database.
    """
    # Safeguard: Do not log if old and new values are exactly the same
    if old_value == new_value and old_value is not None:
        return None

    # Cast values to string to fit varchar fields
    old_str = str(old_value) if old_value is not None else None
    new_str = str(new_value) if new_value is not None else None

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
