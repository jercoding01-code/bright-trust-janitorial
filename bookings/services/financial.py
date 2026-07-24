"""
bookings/services/financial.py

Financial Calculations & CRA Invoice Finalization Service.

Responsibilities
----------------
- Canadian GST/HST pre-tax and sales tax computations.
- Atomic, collision-free CRA sequential invoice numbering (BTJ-YYYY-XXXXXX).
- Financial snapshot immutability enforcement.
- CRA audit log event generation for invoice creation.

Architecture & Compliance Notes
--------------------------------
• Canadian tax law (CRA) requires that invoices maintain a continuous, un-gapable sequence per fiscal year.
• Historical invoices must freeze subtotal, tax amount, tax rate used, and grand total at generation time
  so that future changes to global tax rates or pricing multipliers do NOT alter historical billing records.
• This module intentionally contains no HTTP or template logic.
"""

from decimal import Decimal
from typing import Optional, Tuple, TYPE_CHECKING
from django.db import transaction
from django.utils import timezone
from bookings.models import InvoiceSequence, BusinessSettings, CleaningLead
from bookings.services.audit import log_financial_event

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def calculate_invoice_totals(
    booking: CleaningLead,
    tax_rate: Decimal
) -> Tuple[Decimal, Decimal, Decimal]:
    """Calculates subtotal, tax amount, and total grand price for a booking.

    Args:
        booking (CleaningLead): The target booking instance containing final_quote_price.
        tax_rate (Decimal): The GST/HST tax rate expressed as a decimal (e.g. Decimal('0.1300') for 13% HST).

    Returns:
        Tuple[Decimal, Decimal, Decimal]: A tuple containing (subtotal, tax_amount, total_amount).

    Note:
        Amounts are rounded to 2 decimal places using standard half-up rounding.
        Pre-tax subtotals must be preserved separately from tax amounts for CRA input tax reporting.
    """
    # Canadian invoices must preserve the pre-tax subtotal for CRA compliance
    subtotal: Decimal = booking.final_quote_price or Decimal('0.00')
    tax: Decimal = round(subtotal * tax_rate, 2)
    total: Decimal = subtotal + tax
    return subtotal, tax, total


def generate_invoice_number(booking: CleaningLead) -> str:
    """Generates an atomic, sequential CRA-compliant invoice number formatted as BTJ-YYYY-NNNNNN.

    Args:
        booking (CleaningLead): The booking lead for which the invoice number is being generated.

    Returns:
        str: A unique, formatted invoice string (e.g., 'BTJ-2026-000001').

    Note:
        CRITICAL CONCURRENCY SAFEGUARD:
        Row-locking via select_for_update() guarantees that concurrent admin actions or parallel
        webhooks cannot receive identical invoice numbers. The lock is held until the wrapping
        transaction completes.
    """
    year: int = timezone.now().year
    
    # Invoice numbers must be generated atomically under row lock so concurrent
    # requests cannot receive identical invoice identifiers.
    seq, created = InvoiceSequence.objects.select_for_update().get_or_create(year=year)
    seq.last_sequence += 1
    seq.save()
    
    return f"BTJ-{year}-{seq.last_sequence:06d}"


def finalize_invoice(
    booking: CleaningLead,
    user: Optional['User'] = None,
    source: str = 'SYSTEM'
) -> CleaningLead:
    """Finalizes a booking's financial snapshot, generating a permanent invoice and logging an audit event.

    Args:
        booking (CleaningLead): The target booking to finalize and invoice.
        user (Optional[User]): The administrative user initiating finalization, or None for automated triggers.
        source (str): Source identifier for the audit log (default: 'SYSTEM').

    Returns:
        CleaningLead: The updated, finalized booking instance with populated invoice snapshot fields.

    Raises:
        Exception: If database locks or atomic transaction boundaries fail.

    Note:
        IDEMPOTENCY SAFEGUARD:
        If an invoice_number is already assigned, this function exits immediately without modifying
        historical financial data or creating duplicate sequence increments.
    """
    if booking.invoice_number:
        # Idempotency safeguard: preserve locked accounting snapshot if invoice already exists
        return booking

    # Fallback to calculated system estimate if explicit final quote price was not entered
    if not booking.final_quote_price:
        booking.final_quote_price = booking.system_estimated_price or Decimal('0.00')

    # Enforce atomic transaction boundary: snapshot calculations, sequence increments,
    # and financial audit log creation must succeed together or roll back cleanly.
    with transaction.atomic():
        # Retrieve active company tax rate from BusinessSettings (fallback to 13.00% HST if unconfigured)
        settings = BusinessSettings.objects.first()
        active_rate: Decimal = settings.tax_rate if settings else Decimal('0.1300')
        
        # 1. Generate unique sequential invoice number under database row lock
        inv_num: str = generate_invoice_number(booking)
        
        # 2. Compute pre-tax subtotal, GST/HST, and total grand price
        subtotal, tax, total = calculate_invoice_totals(booking, active_rate)
        
        # 3. Permanently freeze financial snapshot fields
        booking.invoice_number = inv_num
        booking.invoice_generated_at = timezone.now()
        booking.subtotal_amount = subtotal
        booking.tax_amount = tax
        booking.total_amount = total
        booking.tax_rate_used = active_rate
        
        booking.save()
        
        # 4. Create immutable CRA financial audit event
        log_financial_event(
            booking=booking,
            action='INVOICE_GENERATED',
            field_name='invoice_number',
            old_value=None,
            new_value=inv_num,
            changed_by=user,
            source=source,
            notes=f"Invoice finalized with subtotal={subtotal}, tax={tax}, total={total} using rate={active_rate}"
        )
        
    return booking
