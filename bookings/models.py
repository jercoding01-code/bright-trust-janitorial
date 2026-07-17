from django.db import models
from decimal import Decimal

class CleaningLead(models.Model):
    # New fields requested by the owner
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    address = models.CharField(max_length=255)
    email = models.EmailField()
    contact_number = models.CharField(max_length=15)
    square_footage_estimate = models.IntegerField(help_text="Approximate sq. ft.")
    requested_date_time = models.DateTimeField()
    
    # This stores the URL of the uploaded image on ImageKit
    property_photo = models.URLField(max_length=500, blank=True, null=True, help_text="ImageKit URL for client property photo")
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    STATUS_CHOICES = [
        ('NEW', 'New Request'),
        ('CONTACTED', 'Quote Sent'),
        ('SCHEDULED', 'Scheduled'),
        ('COMPLETED', 'Job Done'),
        ('CANCELLED', 'Cancelled'),
        ('CONFIRMED', 'Confirmed'),
        ('IN_PROGRESS', 'In Progress'),
        ('PENDING', 'Pending'),
        ('REJECTED', 'Rejected'),
        ('EXPIRED', 'Expired'),
    ]
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='NEW')

    system_estimated_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # The final price the owner decides on
    final_quote_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, null=True, help_text="Add internal notes about the property condition here.")
    customer_notes = models.TextField(blank=True, null=True, help_text="Specific focus areas or tasks requested by the customer")
    square_checkout_url = models.URLField(blank=True, null=True, max_length=500, help_text="Dynamic Square Canada payment link generated for this quote")
    
    # Custom availability and scheduling support
    service_duration_hours = models.IntegerField(null=True, blank=True, help_text="Duration of service in hours. If blank, defaults to settings.")
    requested_end_time = models.DateTimeField(null=True, blank=True, help_text="Calculated end time of the service.")

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