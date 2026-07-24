import re
import hashlib
from decimal import Decimal
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, timedelta
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings as django_settings
from django.conf import settings
import os
import urllib.parse
import uuid
import requests
import hmac
import time
import logging
from imagekitio import ImageKit

logger_bookings = logging.getLogger('bookings')
logger_payments = logging.getLogger('payments')
logger_webhooks = logging.getLogger('webhooks')
logger_emails = logging.getLogger('emails')


from .decorators import rate_limit
from .models import CleaningLead, BusinessSettings, WebsiteVisit
from .forms import CleaningLeadForm, CleaningLeadDashboardForm, BusinessSettingsForm, UserAccountForm
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash


# --- Public Site Views ---

def track_visit(request):
    try:
        # Extract IP address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
        
        # Create an anonymous hash of the IP for unique visitor metrics (GDPR-friendly)
        ip_hash = hashlib.sha256(ip.encode('utf-8')).hexdigest()
        
        # Store path and ip hash
        WebsiteVisit.objects.create(path=request.path, ip_hash=ip_hash)
    except Exception as e:
        logger_bookings.error(f"Error tracking visit: {e}")


def landing_page(request):
    track_visit(request)
    return render(request, 'index.html')


@rate_limit(limit=30, period=60)
def available_slots_api(request):
    date_str = request.GET.get('date')
    if not date_str:
        return JsonResponse({"error": "Missing date parameter"}, status=400)
    
    try:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)
        
        from .services import get_available_slots_for_date
        slots = get_available_slots_for_date(selected_date)
        
        return JsonResponse({
            "date": date_str,
            "available_slots": slots
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.exception("Error calculating available slots")
        return JsonResponse({
            "error": "Server error during slot calculation",
            "message": str(e)
        }, status=500)


@rate_limit(limit=10, period=60)
def booking_page(request):
    track_visit(request)
    if request.method == 'POST':
        form = CleaningLeadForm(request.POST)
        if form.is_valid():
            try:
                # 1. Save metadata first with validation / conflict checks in a transaction
                lead = form.save(commit=False)
                
                from .services import check_and_reserve_slot
                from django.db import IntegrityError
                
                try:
                    if not check_and_reserve_slot(lead):
                        return JsonResponse(
                            {"error": "This appointment time is no longer available."},
                            status=400
                        )
                    # Log QUOTE_CREATED explicit financial event
                    from bookings.services.audit import log_financial_event
                    log_financial_event(
                        booking=lead,
                        action='QUOTE_CREATED',
                        new_value=lead.system_estimated_price,
                        source='USER',
                        notes=f"Initial quote request submitted by customer. Estimated base price: CA${lead.system_estimated_price}."
                    )
                except IntegrityError:
                    return JsonResponse(
                        {"error": "This appointment time is no longer available."},
                        status=400
                    )
                
                # 2. Intercept up to 4 photos from request.FILES
                uploaded_files = request.FILES.getlist('property_photos')
                
                if len(uploaded_files) > 4:
                    messages.error(request, "You can upload a maximum of 4 photos.")
                    lead.delete()
                    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                        return JsonResponse({"error": "You can upload a maximum of 4 photos."}, status=400)
                    return render(request, 'booking.html', {
                        'form': form,
                        'ik_public_key': getattr(django_settings, 'IMAGEKIT_PUBLIC_KEY', os.environ.get('IMAGEKIT_PUBLIC_KEY', '')),
                        'ik_url_endpoint': getattr(django_settings, 'IMAGEKIT_URL_ENDPOINT', os.environ.get('IMAGEKIT_URL_ENDPOINT', '')),
                    })
                
                first_url = None
                for idx, file_obj in enumerate(uploaded_files):
                    filename = f"before_booking_{lead.pk}_{idx + 1}.jpg"
                    photo_url = upload_file_to_imagekit(file_obj, filename, folder="/client_property_photos/")
                    if photo_url:
                        PhotosLog.objects.create(
                            booking=lead,
                            photo_url=photo_url,
                            photo_type='BEFORE',
                            uploaded_by='CLIENT'
                        )
                        if not first_url:
                            first_url = photo_url
                
                if first_url:
                    lead.property_photo = first_url
                    lead.save()
                    
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"success": True})
                return redirect('booking_success')
            except Exception as e:
                logger_bookings.error(f"Error saving lead: {e}")
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"error": f"An error occurred: {e}"}, status=400)
                messages.error(request, f"An error occurred: {e}")
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"error": form.errors.as_text()}, status=400)
    else:
        form = CleaningLeadForm()
        
    ik_public_key = getattr(django_settings, 'IMAGEKIT_PUBLIC_KEY', os.environ.get('IMAGEKIT_PUBLIC_KEY', ''))
    ik_url_endpoint = getattr(django_settings, 'IMAGEKIT_URL_ENDPOINT', os.environ.get('IMAGEKIT_URL_ENDPOINT', ''))
    
    # Calculate today's date to set min value on frontend
    today_date = timezone.now().date().strftime('%Y-%m-%d')
    
    return render(request, 'booking.html', {
        'form': form,
        'ik_public_key': ik_public_key,
        'ik_url_endpoint': ik_url_endpoint,
        'today_date': today_date,
    })


def booking_success(request):
    return render(request, 'success.html')


def calculate_quote(sqft):
    base_pay = 95.00
    variable_rate = 0.65
    price = base_pay + (float(sqft) * variable_rate)
    return round(price, 2)


# --- Owner Dashboard Views ---

@rate_limit(limit=15, period=60)
def dashboard_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('dashboard_home')
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user.is_staff:
                auth_login(request, user)
                return redirect('dashboard_home')
            else:
                form.add_error(None, "Access denied. Only staff/owners can access the dashboard.")
    else:
        form = AuthenticationForm()
    return render(request, 'dashboard_login.html', {'form': form})


def dashboard_logout(request):
    auth_logout(request)
    return redirect('dashboard_login')


@login_required(login_url='dashboard_login')
def dashboard_home(request):
    if not request.user.is_staff:
        auth_logout(request)
        return redirect('dashboard_login')
        
    query = request.GET.get('q', '')
    status_filter = request.GET.get('status', '')
    
    bookings = CleaningLead.objects.all().order_by('-created_at')
    
    if query:
        bookings = bookings.filter(
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(address__icontains=query) |
            Q(email__icontains=query) |
            Q(contact_number__icontains=query)
        )
    if status_filter:
        bookings = bookings.filter(status=status_filter)
        
    # Bookings metrics
    total_leads = CleaningLead.objects.count()
    new_leads = CleaningLead.objects.filter(status='NEW').count()
    quote_sent = CleaningLead.objects.filter(status='CONTACTED').count()
    scheduled_jobs = CleaningLead.objects.filter(status='SCHEDULED').count()
    completed_jobs = CleaningLead.objects.filter(status='COMPLETED').count()
    
    # Revenue estimate (Scheduled and Completed jobs)
    revenue_scheduled = CleaningLead.objects.filter(status='SCHEDULED')
    revenue_completed = CleaningLead.objects.filter(status='COMPLETED')
    
    total_rev = Decimal('0.00')
    for job in list(revenue_scheduled) + list(revenue_completed):
        if job.final_quote_price and job.final_quote_price > 0:
            total_rev += job.final_quote_price
        elif job.system_estimated_price:
            total_rev += job.system_estimated_price
            
    # Traffic metrics
    total_page_views = WebsiteVisit.objects.count()
    unique_visitors = WebsiteVisit.objects.values('ip_hash').distinct().count()
    
    # Breakdown
    landing_views = WebsiteVisit.objects.filter(path='/').count()
    booking_views = WebsiteVisit.objects.filter(path='/book/').count()
    
    # 7-day traffic chart data (simple list of days and counts)
    today = timezone.now().date()
    traffic_chart = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_start = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
        day_end = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.max.time()))
        count = WebsiteVisit.objects.filter(timestamp__range=(day_start, day_end)).count()
        traffic_chart.append({
            'label': day.strftime('%a'),
            'count': count
        })

    # Calculate monthly transactions (based on finalized invoices)
    finalized_bookings = CleaningLead.objects.exclude(invoice_number__isnull=True).order_by('-invoice_generated_at')
    
    from collections import defaultdict
    monthly_summaries = defaultdict(lambda: {
        'subtotal': Decimal('0.00'),
        'tax': Decimal('0.00'),
        'total': Decimal('0.00'),
        'count': 0
    })
    
    for b in finalized_bookings:
        if b.invoice_generated_at:
            month_key = b.invoice_generated_at.strftime('%Y-%m')
            monthly_summaries[month_key]['subtotal'] += b.subtotal_amount or Decimal('0.00')
            monthly_summaries[month_key]['tax'] += b.tax_amount or Decimal('0.00')
            monthly_summaries[month_key]['total'] += b.total_amount or Decimal('0.00')
            monthly_summaries[month_key]['count'] += 1
            
    monthly_transactions = []
    for key, data in sorted(monthly_summaries.items(), reverse=True):
        year, month = key.split('-')
        monthly_transactions.append({
            'month_name': timezone.datetime(int(year), int(month), 1).strftime('%B %Y'),
            'subtotal': data['subtotal'],
            'tax': data['tax'],
            'total': data['total'],
            'count': data['count']
        })

    context = {
        'bookings': bookings,
        'query': query,
        'status_filter': status_filter,
        'total_leads': total_leads,
        'new_leads': new_leads,
        'quote_sent': quote_sent,
        'scheduled_jobs': scheduled_jobs,
        'completed_jobs': completed_jobs,
        'total_rev': total_rev,
        'total_page_views': total_page_views,
        'unique_visitors': unique_visitors,
        'landing_views': landing_views,
        'booking_views': booking_views,
        'traffic_chart': traffic_chart,
        'monthly_transactions': monthly_transactions,
        'STATUS_CHOICES': CleaningLead.STATUS_CHOICES,
    }
    return render(request, 'dashboard_home.html', context)


@login_required(login_url='dashboard_login')
def dashboard_booking_add(request):
    if not request.user.is_staff:
        auth_logout(request)
        return redirect('dashboard_login')
        
    if request.method == 'POST':
        form = CleaningLeadDashboardForm(request.POST, request.FILES)
        if form.is_valid():
            lead = form.save(commit=False)
            from bookings.services import schedule_admin_booking
            from django.db import IntegrityError
            try:
                success, error_msg = schedule_admin_booking(lead, user=request.user, is_new=True, request_context=request)
                if not success:
                    form.add_error('requested_date_time', error_msg or "This slot conflicts with an existing active booking.")
                    messages.error(request, error_msg or "This slot conflicts with an existing active booking.")
                else:
                    # Intercept files
                    uploaded_files = request.FILES.getlist('property_photos')
                    first_url = None
                    for idx, file_obj in enumerate(uploaded_files[:4]):
                        filename = f"before_booking_{lead.pk}_{idx + 1}.jpg"
                        photo_url = upload_file_to_imagekit(file_obj, filename, folder="/client_property_photos/")
                        if photo_url:
                            PhotosLog.objects.create(
                                booking=lead,
                                photo_url=photo_url,
                                photo_type='BEFORE',
                                uploaded_by='STAFF'
                            )
                            if not first_url:
                                first_url = photo_url
                    if first_url:
                        lead.property_photo = first_url
                        lead.save()
                        
                    messages.success(request, "New booking successfully added.")
                    return redirect('dashboard_home')
            except IntegrityError:
                form.add_error('requested_date_time', "This slot conflicts with an existing active booking.")
                messages.error(request, "This slot conflicts with an existing active booking.")
        else:
            messages.error(request, "Failed to save booking. Please review the highlighted form errors below.")
    else:
        form = CleaningLeadDashboardForm()
        
    return render(request, 'dashboard_booking_form.html', {
        'form': form,
        'action': 'Add New Booking'
    })


@login_required(login_url='dashboard_login')
def dashboard_booking_edit(request, pk):
    if not request.user.is_staff:
        auth_logout(request)
        return redirect('dashboard_login')
        
    lead = get_object_or_404(CleaningLead, pk=pk)
    old_status = lead.status
    
    if request.method == 'POST':
        form = CleaningLeadDashboardForm(request.POST, request.FILES, instance=lead)
        if form.is_valid():
            # Backend Immutability Check
            if lead.invoice_number:
                if (form.cleaned_data.get('final_quote_price') != lead.final_quote_price or
                    form.cleaned_data.get('square_footage_estimate') != lead.square_footage_estimate):
                    form.add_error(None, "Financial snapshots are immutable once an invoice is finalized.")
                    return render(request, 'dashboard_booking_form.html', {
                        'form': form,
                        'lead': lead,
                        'action': 'Edit Booking'
                    })

            updated_lead = form.save(commit=False)
            updated_lead._old_status = old_status
            
            from bookings.services import check_and_reserve_slot, schedule_admin_booking
            from bookings.services.audit import log_financial_event
            from bookings.services.financial import finalize_invoice
            from django.utils import timezone
            from django.db import IntegrityError
            
            try:
                # Handle status transition to SCHEDULED via dedicated service
                if updated_lead.status == 'SCHEDULED' and old_status != 'SCHEDULED':
                    success, error_msg = schedule_admin_booking(updated_lead, user=request.user, is_new=False, request_context=request)
                    if not success:
                        form.add_error('requested_date_time', error_msg or "This slot conflicts with an existing active booking.")
                        return render(request, 'dashboard_booking_form.html', {'form': form, 'lead': lead, 'action': 'Edit Booking'})
                else:
                    if not check_and_reserve_slot(updated_lead):
                        form.add_error('requested_date_time', "This slot conflicts with an existing active booking.")
                        return render(request, 'dashboard_booking_form.html', {'form': form, 'lead': lead, 'action': 'Edit Booking'})
                        
                # Upload photos if present
                uploaded_files = request.FILES.getlist('property_photos')
                first_url = None
                for idx, file_obj in enumerate(uploaded_files[:4]):
                    filename = f"before_booking_{updated_lead.pk}_{idx + 1}.jpg"
                    photo_url = upload_file_to_imagekit(file_obj, filename, folder="/client_property_photos/")
                    if photo_url:
                        PhotosLog.objects.create(
                            booking=updated_lead,
                            photo_url=photo_url,
                            photo_type='BEFORE',
                            uploaded_by='STAFF'
                        )
                        if not first_url:
                            first_url = photo_url
                if first_url:
                    updated_lead.property_photo = first_url
                    
                old_price = lead.final_quote_price
                new_price = updated_lead.final_quote_price
                new_status = updated_lead.status
                old_pay_status = lead.payment_status
                new_pay_status = updated_lead.payment_status

                # Check for price changes
                if old_price != new_price:
                    log_financial_event(
                        booking=updated_lead,
                        action='PRICE_CHANGED',
                        field_name='final_quote_price',
                        old_value=old_price,
                        new_value=new_price,
                        changed_by=request.user,
                        source='USER',
                        notes=f"Admin manually modified final quote price from {old_price} to {new_price}."
                    )

                # Check for payment status changes
                if old_pay_status != new_pay_status:
                    log_financial_event(
                        booking=updated_lead,
                        action='PAYMENT_STATUS_CHANGED' if new_pay_status != 'PAID' else 'PAID_IN_FULL',
                        field_name='payment_status',
                        old_value=old_pay_status,
                        new_value=new_pay_status,
                        changed_by=request.user,
                        source='USER',
                        notes=f"Payment status updated from {old_pay_status} to {new_pay_status}."
                    )
                    if new_pay_status == 'PAID':
                        updated_lead.paid_in_full_at = timezone.now()
                    elif new_pay_status == 'PENDING':
                        updated_lead.deposit_paid_at = None
                        updated_lead.paid_in_full_at = None

                # If status is changing to COMPLETED, finalize the invoice snapshot
                if new_status == 'COMPLETED' and old_status != 'COMPLETED':
                    finalize_invoice(updated_lead, user=request.user, source='USER')
                    
                    log_financial_event(
                        booking=updated_lead,
                        action='STATUS_CHANGED',
                        field_name='status',
                        old_value=old_status,
                        new_value='Job Done',
                        changed_by=request.user,
                        source='USER',
                        notes="Status changed to Job Done (Completed) by admin."
                    )
                    log_financial_event(
                        booking=updated_lead,
                        action='BOOKING_COMPLETED',
                        changed_by=request.user,
                        source='USER',
                        notes="Booking completed by admin."
                    )
                else:
                    if old_status != new_status and new_status != 'SCHEDULED':
                        log_financial_event(
                            booking=updated_lead,
                            action='STATUS_CHANGED',
                            field_name='status',
                            old_value=old_status,
                            new_value=new_status,
                            changed_by=request.user,
                            source='USER',
                            notes=f"Booking status modified from {old_status} to {new_status}."
                        )
                    updated_lead.save()
                    
                messages.success(request, f"Booking for {lead.first_name} {lead.last_name} updated successfully.")
                return redirect('dashboard_home')
            except IntegrityError:
                form.add_error('requested_date_time', "This slot conflicts with an existing active booking.")
    else:
        form = CleaningLeadDashboardForm(instance=lead)
        
    return render(request, 'dashboard_booking_form.html', {
        'form': form,
        'lead': lead,
        'action': 'Edit Booking'
    })


@login_required(login_url='dashboard_login')
def dashboard_booking_delete(request, pk):
    if not request.user.is_staff:
        auth_logout(request)
        return redirect('dashboard_login')
        
    lead = get_object_or_404(CleaningLead, pk=pk)
    name = f"{lead.first_name} {lead.last_name}"
    
    if request.method == 'POST':
        lead.delete()
        messages.success(request, f"Booking for {name} has been successfully deleted.")
        return redirect('dashboard_home')
        
    return render(request, 'dashboard_booking_confirm_delete.html', {
        'lead': lead
    })


@login_required(login_url='dashboard_login')
def dashboard_settings(request):
    if not request.user.is_staff:
        auth_logout(request)
        return redirect('dashboard_login')
        
    settings = BusinessSettings.objects.first()
    if not settings:
        settings = BusinessSettings.objects.create()
        
    if request.method == 'POST':
        form = BusinessSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            form.save()
            messages.success(request, "Business settings updated successfully.")
            return redirect('dashboard_home')
    else:
        form = BusinessSettingsForm(instance=settings)
        
    return render(request, 'dashboard_settings.html', {
        'form': form
    })


def create_square_checkout_link(lead):
    # Only try to create if Square keys are configured in Django settings or environment variables
    access_token = getattr(django_settings, 'SQUARE_ACCESS_TOKEN', os.environ.get('SQUARE_ACCESS_TOKEN', ''))
    location_id = getattr(django_settings, 'SQUARE_LOCATION_ID', os.environ.get('SQUARE_LOCATION_ID', ''))
    environment = getattr(django_settings, 'SQUARE_ENVIRONMENT', os.environ.get('SQUARE_ENVIRONMENT', 'sandbox'))

    if not access_token or not location_id:
        return None
        
    # Calculate 25% downpayment
    price = lead.final_quote_price if (lead.final_quote_price and lead.final_quote_price > 0) else (lead.system_estimated_price if lead.system_estimated_price else Decimal('0.00'))
    downpayment = price * Decimal('0.25')
    downpayment = downpayment.quantize(Decimal('0.01'))
    amount_cents = int(downpayment * 100)
    
    if amount_cents <= 0:
        return None
        
    url = "https://connect.squareup.com/v2/online-checkout/payment-links"
    if environment == 'sandbox':
        url = "https://connect.squareupsandbox.com/v2/online-checkout/payment-links"
        
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Square-Version": "2024-03-20"
    }
    
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "checkout_options": {
            "redirect_url": "https://bright-trust-janitorial.onrender.com/success/"
        },
        "order": {
            "location_id": location_id,
            "reference_id": f"lead_{lead.id}",
            "line_items": [{
                "name": f"25% Downpayment - {lead.service_type} cleaning",
                "quantity": "1",
                "base_price_money": {
                    "amount": amount_cents,
                    "currency": "CAD"
                }
            }]
        }
    }
    
    try:
        response = requests.post(url, json=body, headers=headers, timeout=10)
        if response.status_code == 200 or response.status_code == 201:
            data = response.json()
            checkout_url = data.get('payment_link', {}).get('url')
            if checkout_url:
                lead.square_checkout_url = checkout_url
                lead.save()
                return checkout_url
        else:
            logger_payments.error(f"Square API Error for Lead #{lead.pk}: Status {response.status_code}, Response: {response.text}")
    except Exception as e:
        logger_payments.error(f"Square API Connection Exception for Lead #{lead.pk}: {e}")
    return None


def send_email_via_resend_api(subject, text_content, html_content, to_email):
    from django.conf import settings as django_settings
    
    api_key = getattr(django_settings, 'EMAIL_HOST_PASSWORD', '')
    from_email = getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'info@brighttrustjanitorial.ca')
    
    # Check if local debug mode with console fallback should be used
    if django_settings.DEBUG and not api_key:
        from django.core.mail import EmailMultiAlternatives
        msg = EmailMultiAlternatives(subject, text_content, from_email, [to_email])
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        return {"id": "console_mock_id"}
        
    if not api_key:
        raise ValueError("EMAIL_HOST_PASSWORD (Resend API Key) is not configured in settings.")
        
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
        "text": text_content,
        "reply_to": from_email
    }
    
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    
    if response.status_code not in (200, 201):
        raise Exception(f"Resend API returned status {response.status_code}: {response.text}")
        
    return response.json()


@login_required(login_url='dashboard_login')
def dashboard_send_email(request, pk):
    if not request.user.is_staff:
        auth_logout(request)
        return redirect('dashboard_login')
        
    lead = get_object_or_404(CleaningLead, pk=pk)
    
    if lead.status == 'NEW':
        doc_type = "Quote"
        intro = "Thank you for choosing Bright Trust Janitorial. Please find your service quote below:"
    elif lead.status == 'CONTACTED':
        doc_type = "Quote"
        intro = "Following up on your request. Please find your service quote below:"
    elif lead.status == 'SCHEDULED':
        doc_type = "Service Reminder"
        intro = "We are looking forward to your upcoming cleaning service! Here are the details:"
    elif lead.status == 'COMPLETED':
        doc_type = "Invoice"
        intro = "Thank you for your business! Please find your final invoice below:"
    elif lead.status == 'CANCELLED':
        doc_type = "Cancellation Details"
        intro = "Your booking request has been cancelled. Below are the details of the booking:"
    else:
        doc_type = "Service Details"
        intro = "Please find your service details below:"

    price = lead.final_quote_price if (lead.final_quote_price and lead.final_quote_price > 0) else (lead.system_estimated_price if lead.system_estimated_price else Decimal('0.00'))
    formatted_price = f"${price:,.2f}"
    
    # 12-hour time format (e.g. Jul 20, 2026, 10:00 AM)
    formatted_date_time = lead.requested_date_time.strftime('%b %d, %Y, %I:%M %p')
    
    # Fetch / Generate dynamic Square Checkout link
    payment_link = lead.square_checkout_url
    if not payment_link:
        payment_link = create_square_checkout_link(lead)
        
    # Fallback to settings link if dynamic link failed/is not configured
    if not payment_link:
        biz_settings = BusinessSettings.objects.first()
        payment_link = biz_settings.square_payment_link if biz_settings else None

    subject = f"{doc_type}: Cleaning Services - Bright Trust Janitorial"

    protocol = 'https' if request.is_secure() else 'http'
    host = request.get_host()
    logo_url = f"{protocol}://{host}/static/images/logo.JPEG"
    context = {
        'lead': lead,
        'doc_type': doc_type,
        'intro': intro,
        'formatted_price': formatted_price,
        'formatted_date_time': formatted_date_time,
        'payment_link': payment_link,
        'logo_url': logo_url,
    }

    # Render templates
    html_content = render_to_string('email_quote.html', context)
    
    text_content = (
        f"BRIGHT TRUST JANITORIAL INC.\n"
        f"Phone: (365) 720-1492\n"
        f"Email: brighttrustjanitorial.ca@gmail.com\n"
        f"------------------------------------------\n\n"
        f"Dear {lead.first_name} {lead.last_name},\n\n"
        f"{intro}\n\n"
        f"--- SERVICE SUMMARY ---\n"
        f"Property Size: {lead.square_footage_estimate} sq. ft.\n"
        f"Service Date Requested: {formatted_date_time}\n"
        f"Total {doc_type}: {formatted_price}\n\n"
    )
    
    if payment_link:
        text_content += f"--- SECURE DOWNPAYMENT ---\nTo confirm your booking, please submit your deposit here:\n{payment_link}\n\n"
        
    text_content += (
        f"--- TERMS & CONDITIONS ---\n"
        f"1. This quote/invoice is valid for 30 days.\n"
        f"2. A 25% downpayment is required to confirm the booking. This downpayment is non-refundable, but the booking date can be adjusted.\n"
        f"3. Remaining payment is due upon completion of services.\n\n"
        f"Best regards,\n"
        f"The Bright Trust Janitorial Team"
    )

    email_sent_successfully = False
    
    if django_settings.EMAIL_HOST_USER:
        try:
            send_email_via_resend_api(subject, text_content, html_content, lead.email)
            
            if lead.status == 'NEW':
                lead.status = 'CONTACTED'
                lead.save()
                
            email_sent_successfully = True
            messages.success(request, f"HTML Email successfully sent to {lead.email} via server API.")
        except Exception as e:
            messages.error(request, f"Server Email API failed: {e}. You can use the fallback mailto link below.")
    else:
        if lead.status == 'NEW':
            lead.status = 'CONTACTED'
            lead.save()
        messages.info(request, "Server Email configuration is not configured. Please use the mailto link below.")

    # Pre-generate Mailto fallback parameters
    mailto_body = urllib.parse.quote(text_content)
    mailto_subject = urllib.parse.quote(subject)
    mailto_url = f"mailto:{lead.email}?subject={mailto_subject}&body={mailto_body}"
    
    return render(request, 'dashboard_email_sent.html', {
        'lead': lead,
        'email_sent_successfully': email_sent_successfully,
        'mailto_url': mailto_url,
        'subject': subject,
        'text_content': text_content,
    })


from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse, JsonResponse
import json

@csrf_exempt
def square_webhook(request):
    if request.method == 'POST':
        # Webhook Signature Verification
        from django.conf import settings as django_settings
        sig_key = getattr(django_settings, 'SQUARE_SIGNATURE_KEY', '')
        if sig_key:
            sig_header = request.headers.get('x-square-hmacsha256-signature', '')
            notification_url = request.build_absolute_uri()
            raw_body = request.body
            
            import hmac
            import hashlib
            import base64
            
            payload_to_sign = notification_url.encode('utf-8') + raw_body
            computed_hmac = hmac.new(
                sig_key.encode('utf-8'),
                payload_to_sign,
                hashlib.sha256
            ).digest()
            computed_sig = base64.b64encode(computed_hmac).decode('utf-8')
            
            if not hmac.compare_digest(computed_sig, sig_header):
                logger_webhooks.warning("Square Webhook: Signature verification failed.")
                return HttpResponse(status=401)

        try:
            payload = json.loads(request.body.decode('utf-8'))
            event_type = payload.get('type')
            logger_webhooks.info(f"Square Webhook event received: {event_type}")
            
            # The event for payment or checkout update
            data_obj = payload.get('data', {}).get('object', {})
            
            # Look for reference_id across payment, order, or checkout webhook schemas
            reference_id = None
            payment = data_obj.get('payment', {})
            if payment:
                reference_id = payment.get('reference_id')
                
            if not reference_id:
                order = data_obj.get('order', {})
                if order:
                    reference_id = order.get('reference_id')
                    
            if not reference_id:
                checkout = data_obj.get('checkout', {})
                if checkout:
                    reference_id = checkout.get('reference_id')
                    
            # If reference_id is not directly in the payload, try fetching the order details from Square API
            if not reference_id:
                order_id = None
                if payment:
                    order_id = payment.get('order_id')
                if not order_id:
                    order_updated = data_obj.get('order_updated', {})
                    if order_updated:
                        order_id = order_updated.get('order_id')
                        
                if order_id:
                    from django.conf import settings as django_settings
                    access_token = getattr(django_settings, 'SQUARE_ACCESS_TOKEN', '')
                    environment = getattr(django_settings, 'SQUARE_ENVIRONMENT', 'sandbox')
                    url = f"https://connect.squareup.com/v2/orders/{order_id}"
                    if environment == 'sandbox':
                        url = f"https://connect.squareupsandbox.com/v2/orders/{order_id}"
                        
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                        "Square-Version": "2024-03-20"
                    }
                    try:
                        resp = requests.get(url, headers=headers, timeout=5)
                        if resp.status_code == 200:
                            order_data = resp.json().get('order', {})
                            reference_id = order_data.get('reference_id')
                            logger_webhooks.info(f"Square Webhook: Fetched order {order_id} via API, found reference_id: {reference_id}")
                        else:
                            logger_webhooks.error(f"Square Webhook Order Fetch Error: Status {resp.status_code}, Response: {resp.text}")
                    except Exception as api_err:
                        logger_webhooks.error(f"Square Webhook Order Fetch Exception: {api_err}")
                        
            if reference_id:
                try:
                    cleaned_ref = reference_id
                    if isinstance(cleaned_ref, str) and cleaned_ref.startswith('lead_'):
                        cleaned_ref = cleaned_ref.replace('lead_', '')
                    lead_id = int(cleaned_ref)
                    lead = CleaningLead.objects.get(pk=lead_id)
                    
                    from django.utils import timezone
                    from bookings.services.audit import log_financial_event
                    
                    # Store payment references
                    p_id = payment.get('id') if payment else None
                    o_id = order_id if 'order_id' in locals() and order_id else (payment.get('order_id') if payment else None)
                    if p_id:
                        lead.square_payment_id = p_id
                    if o_id:
                        lead.square_order_id = o_id
                        
                    lead.payment_status = 'DEPOSIT_PAID'
                    lead.deposit_paid_at = timezone.now()
                    
                    # Log DEPOSIT_RECEIVED
                    log_financial_event(
                        booking=lead,
                        action='DEPOSIT_RECEIVED',
                        new_value=payment.get('amount_money', {}).get('amount') if payment else None,
                        source='WEBHOOK',
                        notes=f"Square Webhook downpayment deposit processed. Payment ID: {p_id}"
                    )
                    
                    # Automatically update status to SCHEDULED upon successful payment of quote
                    if lead.status in ['NEW', 'CONTACTED']:
                        old_status = lead.get_status_display()
                        lead.status = 'SCHEDULED'
                        lead.save()
                        
                        log_financial_event(
                            booking=lead,
                            action='STATUS_CHANGED',
                            field_name='status',
                            old_value=old_status,
                            new_value='Scheduled',
                            source='WEBHOOK',
                            notes="Status automatically updated to Scheduled upon downpayment receipt."
                        )
                        logger_webhooks.info(f"Square Webhook: Lead #{lead_id} successfully paid downpayment. Status set to SCHEDULED.")
                    else:
                        lead.save()
                except (ValueError, CleaningLead.DoesNotExist) as e:
                    logger_webhooks.warning(f"Square Webhook Reference Mismatch: Lead ID '{reference_id}' not found: {e}")
                    
            return HttpResponse(status=200)
        except Exception as e:
            logger_webhooks.error(f"Square Webhook Exception: {e}")
            return HttpResponse(status=400)
    return HttpResponse(status=405)


@login_required(login_url='dashboard_login')
def dashboard_account_settings(request):
    if not request.user.is_staff:
        auth_logout(request)
        return redirect('dashboard_login')
        
    user = request.user
    
    if request.method == 'POST':
        if 'update_profile' in request.POST:
            profile_form = UserAccountForm(request.POST, instance=user)
            password_form = PasswordChangeForm(user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Account details successfully updated.")
                return redirect('dashboard_account_settings')
        elif 'change_password' in request.POST:
            profile_form = UserAccountForm(instance=user)
            password_form = PasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                # Keep session active
                update_session_auth_hash(request, user)
                messages.success(request, "Your password was successfully updated.")
                return redirect('dashboard_account_settings')
        else:
            profile_form = UserAccountForm(instance=user)
            password_form = PasswordChangeForm(user)
    else:
        profile_form = UserAccountForm(instance=user)
        password_form = PasswordChangeForm(user)
        
    return render(request, 'dashboard_account_settings.html', {
        'profile_form': profile_form,
        'password_form': password_form,
    })


imagekit = ImageKit(
    public_key=getattr(django_settings, 'IMAGEKIT_PUBLIC_KEY', os.environ.get('IMAGEKIT_PUBLIC_KEY', '')) or 'mock_public_key',
    private_key=getattr(django_settings, 'IMAGEKIT_PRIVATE_KEY', os.environ.get('IMAGEKIT_PRIVATE_KEY', '')) or 'mock_private_key',
    url_endpoint=getattr(django_settings, 'IMAGEKIT_URL_ENDPOINT', os.environ.get('IMAGEKIT_URL_ENDPOINT', '')) or 'https://ik.imagekit.io/mock/'
)


def upload_file_to_imagekit(file_obj, filename, folder="/"):
    import tempfile
    import os
    import uuid
    from imagekitio.models.UploadFileRequestOptions import UploadFileRequestOptions
    
    # 1. Enforce max file size: 10MB
    MAX_SIZE = 10 * 1024 * 1024 # 10MB
    if getattr(file_obj, 'size', 0) > MAX_SIZE:
        logger_bookings.warning(f"File upload rejected: {filename} size exceeds 10MB limit.")
        return None
        
    # 2. Validate MIME type
    content_type = getattr(file_obj, 'content_type', '')
    if content_type and not content_type.startswith('image/'):
        logger_bookings.warning(f"File upload rejected: {filename} MIME type '{content_type}' is not a valid image.")
        return None
        
    # 3. Sanitize filename using secure UUID filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
        ext = '.jpg'
    secure_filename = f"booking_photo_{uuid.uuid4().hex}{ext}"
    
    try:
        # Write file chunks to a secure temporary file to ensure it's a BufferedReader on read
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            for chunk in file_obj.chunks():
                temp_file.write(chunk)
            temp_path = temp_file.name
            
        options = UploadFileRequestOptions(
            folder=folder,
            use_unique_file_name=True
        )
        
        try:
            with open(temp_path, "rb") as bf:
                upload_response = imagekit.upload(
                    file=bf,
                    file_name=secure_filename,
                    options=options
                )
            
            image_url = None
            if hasattr(upload_response, 'url') and upload_response.url:
                image_url = upload_response.url
            elif hasattr(upload_response, 'response_metadata') and upload_response.response_metadata:
                body = getattr(upload_response.response_metadata, 'raw', {})
                image_url = body.get('url')
                
            if image_url:
                return image_url + "?tr=q-auto,f-auto"
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    except Exception as e:
        logger_bookings.error(f"ImageKit SDK Upload Exception: {e}")
        
    return None


def get_imagekit_auth_params():
    private_key = getattr(django_settings, 'IMAGEKIT_PRIVATE_KEY', os.environ.get('IMAGEKIT_PRIVATE_KEY', ''))
    if not private_key:
        private_key = "mock_private_key"
        
    token = str(uuid.uuid4())
    expire = int(time.time() + 1800)
    
    signature = hmac.new(
        private_key.encode('utf-8'),
        f"{token}{expire}".encode('utf-8'),
        hashlib.sha1
    ).hexdigest()
    
    return {
        "token": token,
        "expire": expire,
        "signature": signature
    }

def imagekit_auth(request):
    params = get_imagekit_auth_params()
    return JsonResponse(params)


@rate_limit(limit=15, period=60)
def cleaner_login(request):
    if request.session.get('cleaner_authenticated'):
        return redirect('cleaner_dashboard')
        
    settings_obj = BusinessSettings.objects.first()
    correct_pin = settings_obj.cleaner_pin if settings_obj else "1234"
    
    if request.method == 'POST':
        entered_pin = request.POST.get('pin', '')
        if entered_pin == correct_pin:
            request.session['cleaner_authenticated'] = True
            messages.success(request, "Logged in successfully to Cleaner Portal.")
            return redirect('cleaner_dashboard')
        else:
            messages.error(request, "Invalid Cleaner PIN. Access Denied.")
            
    return render(request, 'cleaner_login.html')


def cleaner_dashboard(request):
    if not request.session.get('cleaner_authenticated'):
        return redirect('cleaner_login')
        
    active_bookings = CleaningLead.objects.filter(
        status='SCHEDULED'
    ).order_by('requested_date_time')
    
    ik_public_key = getattr(django_settings, 'IMAGEKIT_PUBLIC_KEY', os.environ.get('IMAGEKIT_PUBLIC_KEY', ''))
    ik_url_endpoint = getattr(django_settings, 'IMAGEKIT_URL_ENDPOINT', os.environ.get('IMAGEKIT_URL_ENDPOINT', ''))
    
    return render(request, 'cleaner_dashboard.html', {
        'active_bookings': active_bookings,
        'ik_public_key': ik_public_key,
        'ik_url_endpoint': ik_url_endpoint,
    })


def cleaner_logout(request):
    if 'cleaner_authenticated' in request.session:
        del request.session['cleaner_authenticated']
    messages.info(request, "Logged out from Cleaner Portal.")
    return redirect('cleaner_login')


from .models import PhotosLog

def cleaner_upload_after(request, pk):
    if not request.session.get('cleaner_authenticated'):
        return HttpResponse("Unauthorized", status=401)
        
    booking = get_object_or_404(CleaningLead, pk=pk)
    
    if request.method == 'POST':
        after_files = request.FILES.getlist('after_photos')
        if after_files:
            uploaded_urls = []
            for file_obj in after_files:
                filename = f"after_booking_{booking.pk}_{uuid.uuid4().hex[:8]}.jpg"
                photo_url = upload_file_to_imagekit(file_obj, filename, folder="/after_photos/")
                if photo_url:
                    PhotosLog.objects.create(
                        booking=booking,
                        photo_url=photo_url,
                        photo_type='AFTER',
                        uploaded_by='CLEANER'
                    )
                    uploaded_urls.append(photo_url)
            
            if uploaded_urls:
                # 2. Finalize the invoice snapshot & update status to COMPLETED
                from bookings.services.financial import finalize_invoice
                from bookings.services.audit import log_financial_event
                
                old_status = booking.get_status_display()
                booking.status = 'COMPLETED'
                
                # finalizes snapshot amounts and logs INVOICE_GENERATED
                finalize_invoice(booking, source='SYSTEM')
                
                log_financial_event(
                    booking=booking,
                    action='STATUS_CHANGED',
                    field_name='status',
                    old_value=old_status,
                    new_value='Job Done',
                    source='SYSTEM',
                    notes="Status updated to Job Done (Completed) by cleaner completion upload."
                )
                log_financial_event(
                    booking=booking,
                    action='BOOKING_COMPLETED',
                    source='SYSTEM',
                    notes="Booking marked as completed by cleaner."
                )
                
                # 3. Send invoice email automatically
                try:
                    price = booking.final_quote_price if (booking.final_quote_price and booking.final_quote_price > 0) else (booking.system_estimated_price if booking.system_estimated_price else Decimal('0.00'))
                    formatted_price = f"${price:,.2f}"
                    formatted_date_time = booking.requested_date_time.strftime('%b %d, %Y, %I:%M %p')
                    doc_type = "Invoice"
                    intro = "Thank you for your business! Please find your final invoice below:"
                    
                    biz_settings = BusinessSettings.objects.first()
                    review_link = biz_settings.google_review_link if (biz_settings and biz_settings.google_review_link) else "https://g.page/r/your-google-review-link"
                        
                    subject = f"{doc_type}: Cleaning Services - Bright Trust Janitorial"
                    protocol = 'https' if request.is_secure() else 'http'
                    host = request.get_host()
                    logo_url = f"{protocol}://{host}/static/images/logo.JPEG"
                    
                    context = {
                        'lead': booking,
                        'doc_type': doc_type,
                        'intro': intro,
                        'formatted_price': formatted_price,
                        'formatted_date_time': formatted_date_time,
                        'google_review_link': review_link,
                        'logo_url': logo_url,
                        'formatted_subtotal': f"${booking.subtotal_amount:,.2f}" if booking.subtotal_amount else None,
                        'formatted_tax': f"${booking.tax_amount:,.2f}" if booking.tax_amount else None,
                        'formatted_total': f"${booking.total_amount:,.2f}" if booking.total_amount else None,
                        'formatted_tax_rate': f"{booking.tax_rate_used * 100:.1f}%" if booking.tax_rate_used else None,
                    }
                    
                    html_content = render_to_string('email_quote.html', context)
                    text_content = (
                        f"BRIGHT TRUST JANITORIAL INC.\n"
                        f"Phone: (365) 720-1492\n"
                        f"Email: brighttrustjanitorial.ca@gmail.com\n"
                        f"------------------------------------------\n\n"
                        f"Dear {booking.first_name} {booking.last_name},\n\n"
                        f"{intro}\n\n"
                        f"--- SERVICE SUMMARY ---\n"
                        f"Property Size: {booking.square_footage_estimate} sq. ft.\n"
                        f"Service Date Requested: {formatted_date_time}\n"
                        f"Total {doc_type}: {formatted_price}\n\n"
                    )
                    
                    if review_link:
                        text_content += f"--- LEAVE A GOOGLE REVIEW ---\nWe appreciate your support! Please leave us a review here:\n{review_link}\n\n"
                        
                    text_content += (
                        f"--- TERMS & CONDITIONS ---\n"
                        f"1. This quote/invoice is valid for 30 days.\n"
                        f"2. A 25% downpayment is required to confirm the booking. This downpayment is non-refundable, but the booking date can be adjusted.\n"
                        f"3. Remaining payment is due upon completion of services.\n\n"
                        f"Best regards,\n"
                        f"The Bright Trust Janitorial Team"
                    )
                    
                    if django_settings.EMAIL_HOST_USER:
                        send_email_via_resend_api(subject, text_content, html_content, booking.email)
                        logger_emails.info(f"Cleaner Portal: Automated invoice email sent to {booking.email} via API (Booking ID: #{booking.pk})")
                except Exception as mail_err:
                    logger_emails.error(f"Cleaner Portal Email Warning: Failed to send invoice email: {mail_err} (Booking ID: #{booking.pk})")
                    
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"success": True})
                messages.success(request, f"Job Completed! 'After' photo uploaded, status updated to Completed, and Invoice emailed to {booking.email}.")
                return redirect('cleaner_dashboard')
            else:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse({"error": "Failed to upload job completion image to ImageKit. No changes were made."}, status=400)
                messages.error(request, "Error: Failed to upload job completion image to ImageKit. No changes were made.")
        else:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"error": "No job completion file selected."}, status=400)
            messages.error(request, "Error: No job completion file selected.")
            
    return redirect('cleaner_dashboard')


def calendar_events_api(request):
    leads = CleaningLead.objects.exclude(status='CANCELLED').filter(requested_date_time__isnull=False)
    events = []
    
    from django.conf import settings as django_settings
    from datetime import timedelta
    default_duration = getattr(django_settings, 'SERVICE_DURATION_HOURS', 4)
    
    for lead in leads:
        # Determine color based on status
        # Blue for New, Yellow for Quote Sent, Green for Scheduled, Gray for Completed
        color = '#3b82f6'  # Blue for NEW
        if lead.status == 'CONTACTED':
            color = '#eab308'  # Yellow for Quote Sent
        elif lead.status == 'SCHEDULED':
            color = '#10b981'  # Green for Scheduled
        elif lead.status == 'COMPLETED':
            color = '#6b7280'  # Gray for Completed
            
        duration = lead.service_duration_hours or default_duration
        end_time = lead.requested_end_time or (lead.requested_date_time + timedelta(hours=duration))
            
        events.append({
            'id': lead.id,
            'title': f"{lead.first_name} {lead.last_name} ({lead.get_service_type_display()})",
            'start': lead.requested_date_time.isoformat(),
            'end': end_time.isoformat(),
            'color': color,
            'extendedProps': {
                'email': lead.email,
                'phone': lead.contact_number,
                'notes': lead.customer_notes or '',
            }
        })
    return JsonResponse(events, safe=False)


@login_required
def test_smtp_connection(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "Unauthorized"}, status=403)
        
    api_key = getattr(django_settings, 'EMAIL_HOST_PASSWORD', '')
    from_email = getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'info@brighttrustjanitorial.ca')
    
    if not api_key:
        return JsonResponse({
            "status": "error",
            "message": "Resend API key (EMAIL_HOST_PASSWORD) is not configured in settings."
        })
        
    # Test connection to Resend API by sending a simple diagnostic request
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "from": from_email,
        "to": [from_email],
        "subject": "Bright Trust Janitorial - API Verification",
        "text": "This is a diagnostic connection test verifying the HTTPS API path is open."
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        if response.status_code in (200, 201):
            return JsonResponse({
                "status": "success",
                "message": f"Successfully connected to Resend API. Response: {response.text}"
            })
        else:
            return JsonResponse({
                "status": "error",
                "message": f"Resend API returned status {response.status_code}: {response.text}"
            })
    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": f"Resend API Connection failed: {e}"
        })


@login_required
def test_square_connection(request):
    if not request.user.is_staff:
        return JsonResponse({"error": "Unauthorized"}, status=403)
        
    access_token = getattr(django_settings, 'SQUARE_ACCESS_TOKEN', '')
    location_id = getattr(django_settings, 'SQUARE_LOCATION_ID', '')
    environment = getattr(django_settings, 'SQUARE_ENVIRONMENT', 'sandbox')
    
    if not access_token:
        return JsonResponse({
            "status": "error",
            "message": "SQUARE_ACCESS_TOKEN is not configured in settings."
        })
        
    url = "https://connect.squareup.com/v2/locations"
    if environment == 'sandbox':
        url = "https://connect.squareupsandbox.com/v2/locations"
        
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Square-Version": "2024-03-20"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            locations = data.get('locations', [])
            location_ids = [loc.get('id') for loc in locations]
            
            location_matched = location_id in location_ids
            return JsonResponse({
                "status": "success",
                "message": "Successfully authenticated with Square API!",
                "environment": environment,
                "configured_location_id": location_id,
                "configured_location_matched": location_matched,
                "available_location_ids": location_ids
            })
        else:
            return JsonResponse({
                "status": "error",
                "message": f"Square API returned status {response.status_code}: {response.text}"
            })
    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": f"Square API Connection failed: {e}"
        })


@login_required(login_url='dashboard_login')
def dashboard_audit_portal(request):
    if not request.user.is_staff:
        auth_logout(request)
        return redirect('dashboard_login')
        
    from collections import defaultdict
    from bookings.models import CleaningLead, FinancialAuditLog
    
    # Get all finalized bookings
    finalized_bookings = CleaningLead.objects.exclude(invoice_number__isnull=True).order_by('-invoice_generated_at')
    
    # Aggregation in Python for DB engine independence
    monthly_summaries = defaultdict(lambda: {
        'subtotal': Decimal('0.00'),
        'tax': Decimal('0.00'),
        'total': Decimal('0.00'),
        'count': 0
    })
    
    for b in finalized_bookings:
        if b.invoice_generated_at:
            month_key = b.invoice_generated_at.strftime('%Y-%m')
            monthly_summaries[month_key]['subtotal'] += b.subtotal_amount or Decimal('0.00')
            monthly_summaries[month_key]['tax'] += b.tax_amount or Decimal('0.00')
            monthly_summaries[month_key]['total'] += b.total_amount or Decimal('0.00')
            monthly_summaries[month_key]['count'] += 1
            
    monthly_reports = []
    for key, data in sorted(monthly_summaries.items(), reverse=True):
        year, month = key.split('-')
        avg_val = data['total'] / data['count'] if data['count'] > 0 else Decimal('0.00')
        monthly_reports.append({
            'year': year,
            'month': month,
            'month_name': datetime(int(year), int(month), 1).strftime('%B'),
            'subtotal': data['subtotal'],
            'tax': data['tax'],
            'total': data['total'],
            'count': data['count'],
            'avg_value': avg_val
        })
        
    # Recent audit events
    audit_logs = FinancialAuditLog.objects.select_related('booking', 'changed_by').all()[:100]
    
    return render(request, 'dashboard_audit.html', {
        'monthly_reports': monthly_reports,
        'audit_logs': audit_logs,
    })


@login_required(login_url='dashboard_login')
def dashboard_audit_export_csv(request):
    if not request.user.is_staff:
        auth_logout(request)
        return redirect('dashboard_login')
        
    import csv
    from bookings.models import CleaningLead
    
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    leads = CleaningLead.objects.exclude(invoice_number__isnull=True).order_by('-invoice_generated_at')
    
    # Filter by date using timezone-aware conversions
    from django.utils.dateparse import parse_date
    if start_date_str:
        start_date = parse_date(start_date_str)
        if start_date:
            from django.utils.timezone import make_aware, get_current_timezone
            dt = datetime.combine(start_date, datetime.min.time())
            leads = leads.filter(invoice_generated_at__gte=make_aware(dt, get_current_timezone()))
            
    if end_date_str:
        end_date = parse_date(end_date_str)
        if end_date:
            from django.utils.timezone import make_aware, get_current_timezone
            dt = datetime.combine(end_date, datetime.max.time())
            leads = leads.filter(invoice_generated_at__lte=make_aware(dt, get_current_timezone()))
            
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="btj_cra_audit_export.csv"'
    
    # Write UTF-8 BOM so Excel opens it correctly
    response.write('\ufeff'.encode('utf-8'))
    
    writer = csv.writer(response)
    writer.writerow([
        'Invoice Number', 'Invoice Date', 'Booking ID', 'Customer Name',
        'Customer Email', 'Service Address', 'Subtotal', 'Tax Rate Used',
        'Tax Amount', 'Total', 'Payment Status', 'Booking Status'
    ])
    
    for lead in leads:
        inv_date = lead.invoice_generated_at.strftime('%Y-%m-%d %H:%M:%S') if lead.invoice_generated_at else ''
        writer.writerow([
            lead.invoice_number or '',
            inv_date,
            lead.pk,
            f"{lead.first_name} {lead.last_name}",
            lead.email,
            lead.address,
            f"{lead.subtotal_amount:.2f}" if lead.subtotal_amount is not None else '0.00',
            f"{lead.tax_rate_used * 100:.2f}%" if lead.tax_rate_used is not None else '0.00%',
            f"{lead.tax_amount:.2f}" if lead.tax_amount is not None else '0.00',
            f"{lead.total_amount:.2f}" if lead.total_amount is not None else '0.00',
            lead.get_payment_status_display(),
            lead.get_status_display()
        ])
        
    return response


def health_check(request):
    from django.db import connections
    from django.db.utils import OperationalError
    from django.utils import timezone
    from django.conf import settings as django_settings
    
    db_status = "ok"
    try:
        # Trigger a simple cursor call to verify active DB connection
        connections['default'].cursor()
    except OperationalError:
        db_status = "down"
        
    status_code = 200 if db_status == "ok" else 500
    
    # Generate dynamic UTC ISO-8601 timestamp
    timestamp = timezone.now().isoformat()
    if timestamp.endswith('+00:00'):
        timestamp = timestamp[:-6] + 'Z'
        
    # Retrieve environment settings
    env = 'production' if not django_settings.DEBUG else 'development'
    
    return JsonResponse({
        "status": "ok" if db_status == "ok" else "error",
        "application": "ok",
        "database": db_status,
        "environment": env,
        "version": "1.0.0",
        "timestamp": timestamp
    }, status=status_code)


def custom_403(request, exception=None):
    logger_django = logging.getLogger('django')
    logger_django.warning(f"Permission denied: {request.path}")
    return render(request, '403.html', status=403)


def custom_404(request, exception=None):
    logger_django = logging.getLogger('django')
    logger_django.warning(f"Page not found: {request.path}")
    return render(request, '404.html', status=404)


def custom_500(request):
    logger_django = logging.getLogger('django')
    import sys
    exc_type, exc_value, exc_traceback = sys.exc_info()
    logger_django.error(f"Internal server error: {request.path} - Exception: {exc_value}")
    return render(request, '500.html', status=500)
