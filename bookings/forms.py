import re

from django import forms
from .models import CleaningLead

class CleaningLeadForm(forms.ModelForm):
    class Meta:
        model = CleaningLead
        fields = ['first_name', 'last_name', 'address', 'email', 'service_type',
                'contact_number', 'square_footage_estimate', 'requested_date_time', 'property_photo']
        
        widgets = {
            'requested_date_time': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'contact_number': forms.TextInput(attrs={
                'placeholder': '604-555-0123',
                'pattern': '[0-9\-]*',  # This only allows numbers and hyphens
                'title': 'Please enter a valid phone number (e.g., 604-555-0123)'
            }),
            'service_type': forms.Select(attrs={'class': 'form-control'}),
            
        }

def clean_contact_number(self):
        number = self.cleaned_data.get('contact_number')
        # This regex removes everything except digits
        digits_only = re.sub(r'\D', '', number)
        
        # Check if it's exactly 10 digits (Standard Canadian format)
        if len(digits_only) != 10:
            raise forms.ValidationError("Please enter a valid 10-digit Canadian phone number.")
        
        return number