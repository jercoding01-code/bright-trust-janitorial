import re
from django import forms
from .models import CleaningLead, BusinessSettings
from django.contrib.auth.models import User

class CleaningLeadForm(forms.ModelForm):
    class Meta:
        model = CleaningLead
        fields = [
            'first_name', 'last_name', 'address', 'email', 'service_type',
            'contact_number', 'square_footage_estimate', 'requested_date_time', 'property_photo', 'customer_notes'
        ]
        labels = {
            'address': 'Property Address',
        }
        widgets = {
            'requested_date_time': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'contact_number': forms.TextInput(attrs={
                'placeholder': '604-555-0123',
                'pattern': '[0-9-]*',
                'title': 'Please enter a valid phone number (e.g., 604-555-0123)',
                'class': 'form-control'
            }),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'square_footage_estimate': forms.NumberInput(attrs={'class': 'form-control'}),
            'service_type': forms.Select(attrs={'class': 'form-control'}),
            'property_photo': forms.HiddenInput(attrs={'id': 'id_property_photo'}),
            'customer_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'E.g., Please focus on the kitchen grout, clean the inside of the oven...'}),
        }

    def clean_contact_number(self):
        number = self.cleaned_data.get('contact_number')
        digits_only = re.sub(r'\D', '', number)
        if len(digits_only) != 10:
            raise forms.ValidationError("Please enter a valid 10-digit Canadian phone number.")
        return number

    def clean_requested_date_time(self):
        dt = self.cleaned_data.get('requested_date_time')
        if not dt:
            raise forms.ValidationError("Please select a valid date and time slot.")
        
        # Ensure it is timezone-aware based on Django active timezone settings
        from django.utils import timezone
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt


class CleaningLeadDashboardForm(CleaningLeadForm):
    class Meta(CleaningLeadForm.Meta):
        fields = CleaningLeadForm.Meta.fields + ['status', 'final_quote_price', 'notes']
        widgets = {
            **CleaningLeadForm.Meta.widgets,
            'status': forms.Select(attrs={'class': 'form-control'}),
            'final_quote_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class BusinessSettingsForm(forms.ModelForm):
    class Meta:
        model = BusinessSettings
        fields = ['base_fee', 'sqft_multiplier', 'square_payment_link', 'cleaner_pin', 'google_review_link']
        widgets = {
            'base_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'sqft_multiplier': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'square_payment_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://square.link/u/...'}),
            'cleaner_pin': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter 4-digit PIN', 'render_value': True}),
            'google_review_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://g.page/r/...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cleaner_pin'].required = False

    def clean_cleaner_pin(self):
        pin = self.cleaned_data.get('cleaner_pin')
        if not pin:
            if self.instance and self.instance.pk:
                return self.instance.cleaner_pin
            return "1234"
        return pin


class UserAccountForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }