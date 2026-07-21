from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from bookings.models import InvoiceSequence, BusinessSettings
from bookings.services.audit import log_financial_event

def calculate_invoice_totals(booking, tax_rate):
    """
    Given a booking with a final_quote_price, calculates subtotal, tax_amount, and total_amount.
    """
    subtotal = booking.final_quote_price or Decimal('0.00')
    tax = round(subtotal * tax_rate, 2)
    total = subtotal + tax
    return subtotal, tax, total

def generate_invoice_number(booking):
    """
    Locks the sequence record for the current calendar year via select_for_update()
    to safely generate a unique, sequential invoice number.
    Format: BTJ-YYYY-NNNNNN
    """
    year = timezone.now().year
    
    # Lock the sequence row inside the transaction block
    seq, created = InvoiceSequence.objects.select_for_update().get_or_create(year=year)
    seq.last_sequence += 1
    seq.save()
    
    return f"BTJ-{year}-{seq.last_sequence:06d}"

def finalize_invoice(booking, user=None, source='SYSTEM'):
    """
    Finalizes the booking's financial snapshot. Fully idempotent and atomic.
    """
    if booking.invoice_number:
        # If invoice number is already generated, exit early (Idempotency)
        return booking

    # If the booking has no final_quote_price, fallback to system_estimated_price or 0.00
    if not booking.final_quote_price:
        booking.final_quote_price = booking.system_estimated_price or Decimal('0.00')

    with transaction.atomic():
        # Get active tax rate from settings or use fallback
        settings = BusinessSettings.objects.first()
        active_rate = settings.tax_rate if settings else Decimal('0.1300')
        
        # 1. Generate unique sequential invoice number under transaction lock
        inv_num = generate_invoice_number(booking)
        
        # 2. Compute snapshots
        subtotal, tax, total = calculate_invoice_totals(booking, active_rate)
        
        # 3. Save snapshot fields permanently
        booking.invoice_number = inv_num
        booking.invoice_generated_at = timezone.now()
        booking.subtotal_amount = subtotal
        booking.tax_amount = tax
        booking.total_amount = total
        booking.tax_rate_used = active_rate
        
        booking.save()
        
        # 4. Explicitly log invoice generated event
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
