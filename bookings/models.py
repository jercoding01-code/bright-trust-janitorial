from django.db import models
from decimal import Decimal
from django.contrib.auth.models import User

class CleaningLead(models.Model):
    # New fields requested by the owner
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    address = models.CharField(max_length=255)
    email = models.EmailField(db_index=True)
    contact_number = models.CharField(max_length=15)
    square_footage_estimate = models.IntegerField(help_text="Approximate sq. ft.")
    requested_date_time = models.DateTimeField(db_index=True)
    
    # This stores the URL of the uploaded image on ImageKit
    property_photo = models.URLField(max_length=500, blank=True, null=True, help_text="ImageKit URL for client property photo")
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    STATUS_CHOICES = [
        ('NEW', 'New Request'),
        ('CONTACTED', 'Quote Sent'),
        ('SCHEDULED', 'Scheduled'),
        ('COMPLETED', 'Job Done'),
        ('CANCELLED', 'Cancelled'),
    ]
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='NEW', db_index=True)

    system_estimated_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # The final price the owner decides on
    final_quote_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, null=True, help_text="Add internal notes about the property condition here.")
    customer_notes = models.TextField(blank=True, null=True, help_text="Specific focus areas or tasks requested by the customer")
    square_checkout_url = models.URLField(blank=True, null=True, max_length=500, help_text="Dynamic Square Canada payment link generated for this quote")
    
    # Custom availability and scheduling support
    service_duration_hours = models.IntegerField(null=True, blank=True, help_text="Duration of service in hours. If blank, defaults to settings.")
    requested_end_time = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Calculated end time of the service.")

    # Financial snapshots & CRA audit parameters (Immutable after invoice generated)
    subtotal_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tax_rate_used = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    invoice_number = models.CharField(max_length=50, unique=True, null=True, blank=True, db_index=True)
    invoice_generated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    
    # Financial reconciliation timestamps & reference ids
    deposit_paid_at = models.DateTimeField(null=True, blank=True)
    paid_in_full_at = models.DateTimeField(null=True, blank=True)
    square_payment_id = models.CharField(max_length=100, blank=True, null=True)
    square_order_id = models.CharField(max_length=100, blank=True, null=True)
    payment_status = models.CharField(max_length=20, default='PENDING', choices=[
        ('PENDING', 'Pending Downpayment'),
        ('DEPOSIT_PAID', 'Downpayment Paid'),
        ('PAID', 'Paid in Full'),
        ('REFUNDED', 'Refunded')
    ], db_index=True)

    SERVICE_TYPES = [
        ( 'RESIDENTIAL', 'Residential Home' ),
        ( 'COMMERCIAL', 'Clinic/ Office/ Restaurant' ),
        ( 'HOSPITALITY', 'Airbnb/ Cabin/ RV/ Motel' ),
        ( 'CONSTRUCTION', 'Post Construction' ),
    ]
    service_type = models.CharField(max_length=20, choices=SERVICE_TYPES, default='RESIDENTIAL')

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.address}"

    def save(self, *args, **kwargs):
        # Calculate the estimate automatically if it is blank and we have the square footage
        if not self.system_estimated_price and self.square_footage_estimate:
            # Grab the current pricing from BusinessSettings
            settings = BusinessSettings.objects.first()
            
            if settings:
                base = settings.base_fee
                multiplier = settings.sqft_multiplier
            else:
                # Fallback just in case BusinessSettings hasn't been created yet
                base = Decimal('95.00')
                multiplier = Decimal('0.65')

            # Calculate the universal baseline estimate
            self.system_estimated_price = base + (Decimal(self.square_footage_estimate) * multiplier)
            
        # Dynamically set requested_end_time based on duration configuration
        from django.conf import settings as django_settings
        from datetime import timedelta
        duration = self.service_duration_hours or getattr(django_settings, 'SERVICE_DURATION_HOURS', 4)
        if self.requested_date_time:
            self.requested_end_time = self.requested_date_time + timedelta(hours=duration)
            
        # Execute the save
        super().save(*args, **kwargs)


class BusinessSettings(models.Model):
    base_fee = models.DecimalField(max_digits=10, decimal_places=2, default=95.00)
    sqft_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=0.65)
    square_payment_link = models.URLField(blank=True, null=True, help_text="Your Square Canada Online Checkout link (e.g. https://square.link/u/...)")
    cleaner_pin = models.CharField(max_length=10, default="1234", help_text="PIN for cleaners to log in and upload after photos")
    google_review_link = models.URLField(blank=True, null=True, default="https://g.page/r/your-google-review-link", help_text="Your business Google Review page URL")
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0.1300, help_text="Sales tax rate (e.g. 0.1300 for 13% Ontario HST)")

    def save(self, *args, **kwargs):
        # This ensures there is only ever ONE row of settings
        self.pk = 1
        super().save(*args, **kwargs)
        
    class Meta:
        verbose_name_plural = "Business Settings"


class WebsiteVisit(models.Model):
    path = models.CharField(max_length=255)
    ip_hash = models.CharField(max_length=64, db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.path} - {self.timestamp}"


class PhotosLog(models.Model):
    PHOTO_TYPES = [
        ('BEFORE', 'Before Job'),
        ('AFTER', 'After Job'),
    ]
    UPLOADED_BY_CHOICES = [
        ('CLIENT', 'Customer'),
        ('CLEANER', 'Cleaner'),
    ]
    
    booking = models.ForeignKey(CleaningLead, on_delete=models.CASCADE, related_name='photos')
    photo_url = models.URLField(max_length=500)
    photo_type = models.CharField(max_length=10, choices=PHOTO_TYPES, default='BEFORE')
    uploaded_by = models.CharField(max_length=10, choices=UPLOADED_BY_CHOICES, default='CLIENT')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-uploaded_at']
        verbose_name_plural = "Photos Log"

    def __str__(self):
        return f"Photo {self.get_photo_type_display()} for Lead #{self.booking.pk}"


class InvoiceSequence(models.Model):
    year = models.IntegerField(unique=True)
    last_sequence = models.IntegerField(default=0)

    def __str__(self):
        return f"Sequence for {self.year}: {self.last_sequence}"


class FinancialAuditLog(models.Model):
    booking = models.ForeignKey(CleaningLead, on_delete=models.CASCADE, related_name='audit_logs', db_index=True)
    action = models.CharField(max_length=50, db_index=True)
    field_name = models.CharField(max_length=50, null=True, blank=True)
    old_value = models.CharField(max_length=100, null=True, blank=True)
    new_value = models.CharField(max_length=100, null=True, blank=True)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    source = models.CharField(max_length=20, default='SYSTEM')
    schema_version = models.PositiveSmallIntegerField(default=1)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} on Booking #{self.booking.pk} at {self.timestamp}"