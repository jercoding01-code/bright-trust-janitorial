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
    
    # This stores the path to the uploaded image
    property_photo = models.ImageField(upload_to='property_photos/', blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    STATUS_CHOICES = [
        ('NEW', 'New Request'),
        ('CONTACTED', 'Quote Sent'),
        ('SCHEDULED', 'Scheduled'),
        ('COMPLETED', 'Job Done'),
        ('CANCELLED', 'Cancelled'),
    ]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='NEW')

    system_estimated_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # The final price the owner decides on
    final_quote_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, null=True, help_text="Add internal notes about the property condition here.")
    square_checkout_url = models.URLField(blank=True, null=True, max_length=500, help_text="Dynamic Square Canada payment link generated for this quote")
    
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
            
        # Execute the save
        super().save(*args, **kwargs)


class BusinessSettings(models.Model):
    base_fee = models.DecimalField(max_digits=10, decimal_places=2, default=95.00)
    sqft_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=0.65)
    square_payment_link = models.URLField(blank=True, null=True, help_text="Your Square Canada Online Checkout link (e.g. https://square.link/u/...)")

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