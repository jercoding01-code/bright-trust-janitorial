from datetime import date, datetime, timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.db import connection, IntegrityError
from django.conf import settings
from .models import CleaningLead
from .services import get_available_slots_for_date, check_and_reserve_slot

class SchedulingSystemTests(TestCase):
    def setUp(self):
        # Ensure we have clean state
        CleaningLead.objects.all().delete()
        self.tz = timezone.get_current_timezone()

    def test_self_conflict_on_edit(self):
        """
        A test editing an existing booking without changing its time,
        confirming it saves without a false self-conflict.
        """
        dt = timezone.make_aware(datetime(2026, 7, 20, 10, 0, 0), self.tz)
        lead = CleaningLead(
            first_name="John",
            last_name="Doe",
            address="123 Main St",
            email="john@example.com",
            contact_number="6045550123",
            square_footage_estimate=1000,
            requested_date_time=dt,
            status="SCHEDULED"
        )
        
        # Save first time
        success = check_and_reserve_slot(lead)
        self.assertTrue(success)
        self.assertEqual(lead.status, "SCHEDULED")
        
        # Edit some details without changing time, and save again
        lead.first_name = "Johnny"
        success2 = check_and_reserve_slot(lead)
        self.assertTrue(success2)
        self.assertEqual(CleaningLead.objects.get(pk=lead.pk).first_name, "Johnny")

    def test_midnight_spanning_conflict(self):
        """
        A test confirming a booking placed at 23:00 correctly blocks
        00:00–02:00 the next day (duration spanning midnight), since operation is 24/7.
        """
        # Booking starts at 23:00 on July 20th, ends at 03:00 on July 21st
        dt = timezone.make_aware(datetime(2026, 7, 20, 23, 0, 0), self.tz)
        lead = CleaningLead(
            first_name="Jane",
            last_name="Doe",
            address="456 Elm St",
            email="jane@example.com",
            contact_number="6045550123",
            square_footage_estimate=1500,
            requested_date_time=dt,
            status="SCHEDULED"
        )
        check_and_reserve_slot(lead)
        
        # Candidate slots on July 21st:
        # slot 00:00 ends 04:00 (overlaps with 23:00-03:00) -> should be blocked
        # slot 01:00 ends 05:00 (overlaps with 23:00-03:00) -> should be blocked
        # slot 02:00 ends 06:00 (overlaps with 23:00-03:00) -> should be blocked
        # slot 03:00 ends 07:00 (no overlap with 23:00-03:00) -> should be available
        
        next_day = date(2026, 7, 21)
        slots = get_available_slots_for_date(next_day)
        
        # Assertions
        self.assertNotIn("00:00", slots)
        self.assertNotIn("01:00", slots)
        self.assertNotIn("02:00", slots)
        self.assertIn("03:00", slots)

    def test_forced_double_booking_rejection_at_db_level(self):
        """
        A test confirming the UniqueConstraint (or equivalent) actually
        rejects a forced double-insert at the DB level, run against Postgres.
        """
        dt = timezone.make_aware(datetime(2026, 7, 20, 14, 0, 0), self.tz)
        
        lead1 = CleaningLead.objects.create(
            first_name="Client1",
            last_name="Test",
            address="Suite 1",
            email="c1@example.com",
            contact_number="6045550123",
            square_footage_estimate=1000,
            requested_date_time=dt,
            requested_end_time=dt + timedelta(hours=4),
            status="SCHEDULED"
        )
        
        # Overlapping booking starting at 15:00
        dt_overlap = dt + timedelta(hours=1)
        lead2 = CleaningLead(
            first_name="Client2",
            last_name="Test",
            address="Suite 2",
            email="c2@example.com",
            contact_number="6045550123",
            square_footage_estimate=1200,
            requested_date_time=dt_overlap,
            requested_end_time=dt_overlap + timedelta(hours=4),
            status="SCHEDULED"
        )
        
        if connection.vendor == 'postgresql':
            with self.assertRaises(IntegrityError):
                lead2.save()
        else:
            # On SQLite it will save successfully since btree_gist exclusion
            # constraint is postgres-only, but check_and_reserve_slot must catch it
            success = check_and_reserve_slot(lead2)
            self.assertFalse(success)

    def test_null_end_time_handled_safely(self):
        """
        A test confirming that database rows with NULL/None requested_end_time values
        do not crash the slot calculation logic or the reservation engine.
        """
        dt = timezone.make_aware(datetime(2026, 7, 20, 10, 0, 0), self.tz)
        
        # Bypass the standard save routine (which populates requested_end_time)
        # by calling bulk_create or force updating column to None
        lead = CleaningLead.objects.create(
            first_name="ClientNull",
            last_name="Test",
            address="Suite N",
            email="null@example.com",
            contact_number="6045550123",
            square_footage_estimate=1000,
            requested_date_time=dt,
            status="SCHEDULED"
        )
        CleaningLead.objects.filter(pk=lead.pk).update(requested_end_time=None)
        
        # Check slot availability works without NoneType / TypeError crash
        slots = get_available_slots_for_date(date(2026, 7, 20))
        self.assertNotIn("10:00", slots)  # The overlapping slots should still be blocked safely!
        
        # Check checking a new slot against this null-end-time row works without crashing
        lead2 = CleaningLead(
            first_name="ClientNew",
            last_name="Test",
            address="Suite New",
            email="new@example.com",
            contact_number="6045550123",
            square_footage_estimate=1000,
            requested_date_time=dt,
            status="SCHEDULED"
        )
        success = check_and_reserve_slot(lead2)
        self.assertFalse(success)  # Should fail since there's an overlap, but NOT crash


class ProductionReadinessTests(TestCase):
    def test_health_check_endpoint(self):
        """Confirm /health/ endpoint returns 200 OK with correct JSON keys."""
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'ok')
        self.assertEqual(data.get('database'), 'ok')
        self.assertEqual(data.get('application'), 'ok')

    def test_file_uploader_validations(self):
        """Confirm file uploader validation limits size and MIME type."""
        from .views import upload_file_to_imagekit
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        # 1. Test image with size > 10MB is rejected
        large_file = SimpleUploadedFile("large.png", b"x" * (11 * 1024 * 1024), content_type="image/png")
        url = upload_file_to_imagekit(large_file, "large.png")
        self.assertIsNone(url)

        # 2. Test non-image file is rejected
        text_file = SimpleUploadedFile("test.txt", b"hello world", content_type="text/plain")
        url = upload_file_to_imagekit(text_file, "test.txt")
        self.assertIsNone(url)

    def test_webhook_signature_verification(self):
        """Confirm Square webhook verification blocks unauthorized requests when key is set."""
        from django.test import override_settings
        
        # When signature key is set, request with no signature header must be rejected with 401
        with override_settings(SQUARE_SIGNATURE_KEY="test_sig_key"):
            response = self.client.post('/payments/square-webhook/', data='{"test": 1}', content_type="application/json")
            self.assertEqual(response.status_code, 401)


class FinancialComplianceTests(TestCase):
    def setUp(self):
        CleaningLead.objects.all().delete()
        from django.contrib.auth.models import User
        User.objects.all().delete()
        from bookings.models import BusinessSettings
        BusinessSettings.objects.all().delete()
        self.settings = BusinessSettings.objects.create(
            base_fee=Decimal('100.00'),
            sqft_multiplier=Decimal('0.50'),
            tax_rate=Decimal('0.1300')
        )
        self.tz = timezone.get_current_timezone()
        self.dt = timezone.make_aware(datetime(2026, 7, 20, 10, 0, 0), self.tz)
        self.lead = CleaningLead.objects.create(
            first_name="Test",
            last_name="Account",
            address="100 Tax St",
            email="tax@example.com",
            contact_number="6045550123",
            square_footage_estimate=1000,
            requested_date_time=self.dt,
            final_quote_price=Decimal('200.00'),
            status="SCHEDULED"
        )

    def test_invoice_totals_calculation(self):
        """Confirm calculate_invoice_totals correctly computes pre-tax, tax, and total."""
        from bookings.services.financial import calculate_invoice_totals
        subtotal, tax, total = calculate_invoice_totals(self.lead, Decimal('0.1300'))
        self.assertEqual(subtotal, Decimal('200.00'))
        self.assertEqual(tax, Decimal('26.00'))
        self.assertEqual(total, Decimal('226.00'))

    def test_invoice_finalization_is_idempotent(self):
        """Confirm finalize_invoice only generates invoice number once and is idempotent."""
        from bookings.services.financial import finalize_invoice
        finalize_invoice(self.lead)
        inv_num = self.lead.invoice_number
        self.assertTrue(inv_num.startswith('BTJ-2026-'))
        
        # Call it again and verify nothing changes
        finalize_invoice(self.lead)
        self.assertEqual(self.lead.invoice_number, inv_num)

    def test_sequence_generator_uniqueness(self):
        """Confirm sequence generator yields sequentially unique numbers."""
        from bookings.services.financial import generate_invoice_number
        num1 = generate_invoice_number(self.lead)
        num2 = generate_invoice_number(self.lead)
        self.assertNotEqual(num1, num2)

    def test_historical_tax_rates_remain_unchanged(self):
        """Confirm historical invoices remain unaffected by future tax rate updates in BusinessSettings."""
        from bookings.services.financial import finalize_invoice
        finalize_invoice(self.lead)
        self.assertEqual(self.lead.tax_rate_used, Decimal('0.1300'))
        
        # Modify settings tax rate to 15%
        self.settings.tax_rate = Decimal('0.1500')
        self.settings.save()
        
        # Re-fetch from db and assert lead's rate remains 13%
        lead_refetched = CleaningLead.objects.get(pk=self.lead.pk)
        self.assertEqual(lead_refetched.tax_rate_used, Decimal('0.1300'))

    def test_csv_export_format_and_headers(self):
        """Confirm CSV export matches layout and features UTF-8 BOM byte order marks."""
        from bookings.services.financial import finalize_invoice
        finalize_invoice(self.lead)
        
        # Mock request to CSV exporter
        from django.contrib.auth.models import User
        admin_user = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.client.force_login(admin_user)
        
        response = self.client.get('/dashboard/audit/export/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        
        # Check UTF-8 BOM
        content = response.content
        self.assertTrue(content.startswith(b'\xef\xbb\xbf'))


class AdminSchedulingWorkflowTests(TestCase):
    def setUp(self):
        CleaningLead.objects.all().delete()
        from django.contrib.auth.models import User
        User.objects.all().delete()
        self.admin = User.objects.create_superuser('admin_sched', 'admin_sched@example.com', 'password')
        self.tz = timezone.get_current_timezone()
        self.dt = timezone.make_aware(datetime(2026, 8, 1, 10, 0, 0), self.tz)

    def test_dashboard_form_initial_defaults_for_new_lead(self):
        """Confirm CleaningLeadDashboardForm defaults status to SCHEDULED and payment_status to PENDING for new admin bookings."""
        from bookings.forms import CleaningLeadDashboardForm
        form = CleaningLeadDashboardForm()
        self.assertEqual(form.fields['status'].initial, 'SCHEDULED')
        self.assertEqual(form.fields['payment_status'].initial, 'PENDING')

    def test_schedule_admin_booking_service_success(self):
        """Confirm schedule_admin_booking locks slot, initializes PENDING payment status, and creates audit log."""
        from bookings.services import schedule_admin_booking
        from bookings.models import FinancialAuditLog
        lead = CleaningLead(
            first_name="AdminPhone",
            last_name="Customer",
            address="500 Phone St",
            email="phone@example.com",
            contact_number="6045550199",
            square_footage_estimate=1000,
            requested_date_time=self.dt,
            status="SCHEDULED"
        )
        success, error = schedule_admin_booking(lead, user=self.admin, is_new=True)
        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(lead.status, "SCHEDULED")
        self.assertEqual(lead.payment_status, "PENDING")
        self.assertIsNotNone(lead.pk)
        
        # Verify audit logs
        logs = FinancialAuditLog.objects.filter(booking=lead)
        self.assertTrue(logs.filter(action='QUOTE_CREATED').exists())
        self.assertTrue(logs.filter(action='STATUS_CHANGED').exists())

    def test_schedule_admin_booking_slot_conflict_rollback(self):
        """Confirm slot conflict prevents booking save and returns error without partial DB writes."""
        from bookings.services import schedule_admin_booking
        # Create existing scheduled job
        CleaningLead.objects.create(
            first_name="Existing",
            last_name="Job",
            address="100 Busy St",
            email="busy@example.com",
            contact_number="6045550111",
            square_footage_estimate=1000,
            requested_date_time=self.dt,
            status="SCHEDULED"
        )
        
        # Attempt to schedule overlapping job
        competing_lead = CleaningLead(
            first_name="Conflict",
            last_name="Job",
            address="102 Busy St",
            email="conflict@example.com",
            contact_number="6045550222",
            square_footage_estimate=1000,
            requested_date_time=self.dt,
            status="SCHEDULED"
        )
        success, error = schedule_admin_booking(competing_lead, user=self.admin, is_new=True)
        self.assertFalse(success)
        self.assertIsNotNone(error)
        self.assertIsNone(competing_lead.pk)

