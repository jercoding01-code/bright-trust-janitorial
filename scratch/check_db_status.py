import os
import sys
import django

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BrightTrustJanitorial.settings')
django.setup()

from bookings.models import CleaningLead, BusinessSettings

print("=== BUSINESS SETTINGS ===")
settings = BusinessSettings.objects.first()
if settings:
    print(f"Cleaner PIN: '{settings.cleaner_pin}'")
    print(f"Base Fee: {settings.base_fee}")
    print(f"Google Review Link: '{settings.google_review_link}'")
else:
    print("No BusinessSettings record found!")

print("\n=== BOOKINGS STATUS COUNT ===")
from django.db.models import Count
stats = CleaningLead.objects.values('status').annotate(count=Count('id'))
for stat in stats:
    print(f"Status: {stat['status']} - Count: {stat['count']}")

print("\n=== SCHEDULED BOOKINGS DETAILS ===")
scheduled = CleaningLead.objects.filter(status='SCHEDULED')
for s in scheduled:
    print(f"ID: {s.pk} - Name: {s.first_name} {s.last_name} - Date: {s.requested_date_time}")
