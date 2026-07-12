import re
from django import forms
from .models import CleaningLead, BusinessSettings

class CleaningLeadForm(forms.ModelForm):
    class Meta:
        model = CleaningLead
        fields = [
            'first_name', 'last_name', 'address', 'email', 'service_type',
            'contact_number', 'square_footage_estimate', 'requested_date_time', 'property_photo'
        ]
        widgets = {
            'requested_date_time': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'contact_number': forms.TextInput(attrs={
                'placeholder': '604-555-0123',
                'pattern': '[0-9\-]*',
                'title': 'Please enter a valid phone number (e.g., 604-555-0123)',
                'class': 'form-control'
            }),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'square_footage_estimate': forms.NumberInput(attrs={'class': 'form-control'}),
            'service_type': forms.Select(attrs={'class': 'form-control'}),
            'property_photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def clean_contact_number(self):
        number = self.cleaned_data.get('contact_number')
        digits_only = re.sub(r'\D', '', number)
        if len(digits_only) != 10:
            raise forms.ValidationError("Please enter a valid 10-digit Canadian phone number.")
        return number


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
        fields = ['base_fee', 'sqft_multiplier', 'square_payment_link']
        widgets = {
            'base_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'sqft_multiplier': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'square_payment_link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://square.link/u/...'}),
        }