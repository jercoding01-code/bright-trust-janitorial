from django.contrib import admin
from .models import CleaningLead, BusinessSettings
from django.utils.html import format_html
from decimal import Decimal

@admin.register(CleaningLead)
class CleaningLeadAdmin(admin.ModelAdmin):
    list_display = (
        'first_name', 'last_name', 'service_type', 'address', 
        'contact_number', 'square_footage_estimate', 
        'system_estimated_price', 'status', 'final_quote_price',
        'email_quote_link'
    )
    list_editable = ('final_quote_price', 'status') 
    list_filter = ('status', 'service_type')

    def email_quote_link(self, obj):
        # 1. Price Logic
        final = obj.final_quote_price
        system = obj.system_estimated_price
        price = final if (final and final > 0) else (system if system else Decimal('0.00'))
        
        if isinstance(price, (int, float, Decimal)):
            formatted_price = f"${price:,.2f}"
        else:
            formatted_price = "$0.00"
            
        # 2. Dynamic Status Logic (Color, Text, and Document Type)
        if obj.status == 'NEW':
            btn_color = "#3164e8"  # Bright Blue
            btn_text = "Send Quote"
            doc_type = "Quote"
            intro = "Thank you for choosing Bright Trust Janitorial. Please find your service quote below:"
        elif obj.status == 'CONTACTED':
            btn_color = "#6c757d"  # Grey
            btn_text = "Resend Quote"
            doc_type = "Quote"
            intro = "Following up on your request. Please find your service quote below:"
        elif obj.status == 'SCHEDULED':
            btn_color = "#17a2b8"  # Teal
            btn_text = "Send Reminder"
            doc_type = "Service Reminder"
            intro = "We are looking forward to your upcoming cleaning service! Here are the details:"
        elif obj.status == 'COMPLETED':
            btn_color = "#28a745"  # Green
            btn_text = "Send Invoice"
            doc_type = "Invoice"
            intro = "Thank you for your business! Please find your final invoice below:"
        elif obj.status == 'CANCELLED':
            # Remove the button entirely and just show text
            return format_html('<span style="color:#dc3545; font-weight:bold;">{}</span>', 'Cancelled')  
        else:
            btn_color = "#3164e8"
            btn_text = "Send Email"
            doc_type = "Details"
            intro = "Please find your service details below:"

        # 3. Construct the Email
        subject = f"{doc_type}: Cleaning Services - Bright Trust Janitorial"
        
        header = (
            "BRIGHT TRUST JANITORIAL INC. \n"
            "Phone: (365) 720-1492\n"
            "Email: brighttrustjanitorial.ca@gmail.com\n"
            "------------------------------------------\n"
        )
        
        body = (
            f"{header}\n"
            f"Dear {obj.first_name} {obj.last_name},\n\n"
            f"{intro}\n\n"
            f"--- SERVICE SUMMARY ---\n"
            f"Property Size: {obj.square_footage_estimate} sq. ft.\n"
            f"Service Date Requested: {obj.requested_date_time}\n"
            f"Total {doc_type}: {formatted_price}\n\n"
            f"--- TERMS & CONDITIONS ---\n"
            f"1. This quote/invoice is valid for 30 days.\n"
            f"2. Payment is due upon completion of services.\n\n"
            f"Best regards,\n"
            f"The Bright Trust Janitorial Team"
        )
        
        return format_html(
            '<a href="mailto:{}?subject={}&body={}" style="background:{}; color:white; padding:5px 10px; border-radius:3px; text-decoration:none; white-space:nowrap;">{}</a>',
            obj.email, subject, body.replace('\n', '%0A'), btn_color, btn_text
        )
    
    email_quote_link.short_description = "Actions"
@admin.register(BusinessSettings)
class BusinessSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        # Prevent creating multiple setting rows
        return not BusinessSettings.objects.exists()