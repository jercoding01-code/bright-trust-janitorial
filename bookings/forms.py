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
        digits_only = re.sub(r'\D', '', str(number or ''))
        if len(digits_only) == 11 and digits_only.startswith('1'):
            digits_only = digits_only[1:]
        if len(digits_only) != 10:
            raise forms.ValidationError("Please enter a valid 10-digit phone number.")
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
        fields = CleaningLeadForm.Meta.fields + ['status', 'final_quote_price', 'notes', 'payment_status', 'assigned_cleaner']
        widgets = {
            **CleaningLeadForm.Meta.widgets,
            'status': forms.Select(attrs={'class': 'form-control'}),
            'final_quote_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'payment_status': forms.Select(attrs={'class': 'form-control'}),
            'assigned_cleaner': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from bookings.models import CleanerProfile, models
        if not self.instance or not self.instance.pk:
            if 'status' in self.fields:
                self.fields['status'].initial = 'SCHEDULED'
            if 'payment_status' in self.fields:
                self.fields['payment_status'].initial = 'PENDING'
                
        # Filter assigned cleaner dropdown to active & available cleaners
        available_cleaners = CleanerProfile.objects.filter(is_active=True, availability_status='AVAILABLE')
        if self.instance and self.instance.assigned_cleaner:
            available_cleaners = CleanerProfile.objects.filter(
                models.Q(pk=self.instance.assigned_cleaner.pk) |
                models.Q(is_active=True, availability_status='AVAILABLE')
            )
        self.fields['assigned_cleaner'].queryset = available_cleaners
        self.fields['assigned_cleaner'].required = False
        self.fields['assigned_cleaner'].label = "Assigned Cleaner"
                
        if self.instance and (self.instance.invoice_number or self.instance.status == 'COMPLETED'):
            # Enforce immutability / completed job lock
            for field in ['final_quote_price', 'square_footage_estimate', 'service_type', 'assigned_cleaner']:
                if field in self.fields:
                    self.fields[field].disabled = True
                    self.fields[field].required = False


class CleanerProfileAdminForm(forms.ModelForm):
    pin = forms.CharField(
        max_length=10,
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter 6-digit PIN'}),
        help_text="Enter 6-digit numeric PIN. Leave blank to keep existing PIN when editing."
    )

    class Meta:
        from bookings.models import CleanerProfile
        model = CleanerProfile
        fields = ['name', 'phone', 'email', 'is_active', 'availability_status', 'hourly_rate', 'hire_date', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '604-555-0199'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'cleaner@example.com'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'availability_status': forms.Select(attrs={'class': 'form-control'}),
            'hourly_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'hire_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_phone(self):
        from bookings.models import CleanerProfile
        phone = self.cleaned_data.get('phone')
        digits_only = re.sub(r'\D', '', str(phone or ''))
        if len(digits_only) == 11 and digits_only.startswith('1'):
            digits_only = digits_only[1:]
        if len(digits_only) != 10:
            raise forms.ValidationError("Please enter a valid 10-digit phone number.")
        
        # Check uniqueness against other cleaners
        qs = CleanerProfile.objects.filter(phone=digits_only)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Another cleaner is already registered with this phone number.")
        return digits_only

    def clean_pin(self):
        pin = self.cleaned_data.get('pin')
        if not pin:
            if not self.instance or not self.instance.pk:
                raise forms.ValidationError("A PIN (minimum 6 digits) is required when creating a new cleaner.")
            return None
        digits_only = re.sub(r'\D', '', str(pin))
        if len(digits_only) < 6 or len(digits_only) > 10:
            raise forms.ValidationError("PIN must contain between 6 and 10 numeric digits.")
        return digits_only

    def save(self, commit=True):
        cleaner = super().save(commit=False)
        pin = self.cleaned_data.get('pin')
        if pin:
            cleaner.set_pin(pin)
        if commit:
            cleaner.save()
        return cleaner


class BusinessSettingsForm(forms.ModelForm):
    class Meta:
        model = BusinessSettings
        fields = ['base_fee', 'sqft_multiplier', 'square_payment_link', 'cleaner_pin', 'google_review_link', 'tax_rate']
        widgets = {
            'base_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'sqft_multiplier': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'square_payment_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://square.link/u/...'}),
            'cleaner_pin': forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter 4-digit PIN', 'render_value': True}),
            'google_review_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://g.page/r/...'}),
            'tax_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.0001'}),
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