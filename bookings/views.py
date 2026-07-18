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
from imagekitio import ImageKit


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
        print(f"Error tracking visit: {e}")


def landing_page(request):
    track_visit(request)
    return render(request, 'index.html')


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
                print(f"Error saving lead: {e}")
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
            from .services import check_and_reserve_slot
            from django.db import IntegrityError
            try:
                if not check_and_reserve_slot(lead):
                    form.add_error('requested_date_time', "This slot conflicts with an existing active booking.")
                else:
                    messages.success(request, "New booking successfully added.")
                    return redirect('dashboard_home')
            except IntegrityError:
                form.add_error('requested_date_time', "This slot conflicts with an existing active booking.")
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
    
    if request.method == 'POST':
        form = CleaningLeadDashboardForm(request.POST, request.FILES, instance=lead)
        if form.is_valid():
            updated_lead = form.save(commit=False)
            from .services import check_and_reserve_slot
            from django.db import IntegrityError
            try:
                if not check_and_reserve_slot(updated_lead):
                    form.add_error('requested_date_time', "This slot conflicts with an existing active booking.")
                else:
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
            print(f"Square API Error: Status {response.status_code}, Response: {response.text}")
    except Exception as e:
        print(f"Square API Connection Exception: {e}")
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
        try:
            payload = json.loads(request.body.decode('utf-8'))
            event_type = payload.get('type')
            
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
                    
            if reference_id:
                try:
                    cleaned_ref = reference_id
                    if isinstance(cleaned_ref, str) and cleaned_ref.startswith('lead_'):
                        cleaned_ref = cleaned_ref.replace('lead_', '')
                    lead_id = int(cleaned_ref)
                    lead = CleaningLead.objects.get(pk=lead_id)
                    # Automatically update status to SCHEDULED upon successful payment of quote
                    if lead.status in ['NEW', 'CONTACTED']:
                        lead.status = 'SCHEDULED'
                        lead.save()
                        print(f"Square Webhook: Lead #{lead_id} successfully paid downpayment. Status set to SCHEDULED.")
                except (ValueError, CleaningLead.DoesNotExist) as e:
                    print(f"Square Webhook Reference Mismatch: Lead ID '{reference_id}' not found: {e}")
                    
            return HttpResponse(status=200)
        except Exception as e:
            print(f"Square Webhook Exception: {e}")
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
    try:
        file_content = file_obj.read()
        file_obj.seek(0)  # Reset pointer
        
        upload_response = imagekit.upload_file(
            file=file_content,
            file_name=filename,
            options={
                "folder": folder,
                "use_unique_file_name": True
            }
        )
        
        image_url = None
        if hasattr(upload_response, 'url') and upload_response.url:
            image_url = upload_response.url
        elif hasattr(upload_response, 'response_metadata') and upload_response.response_metadata:
            body = getattr(upload_response.response_metadata, 'raw', {})
            image_url = body.get('url')
            
        if image_url:
            return image_url + "?tr=q-auto,f-auto"
    except Exception as e:
        print(f"ImageKit SDK Upload Exception: {e}")
        
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
        status__in=['NEW', 'CONTACTED', 'SCHEDULED']
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
        after_file = request.FILES.get('after_photo')
        if after_file:
            filename = f"after_booking_{booking.pk}_{int(time.time())}.jpg"
            photo_url = upload_file_to_imagekit(after_file, filename, folder="/after_photos/")
            
            if photo_url:
                # 1. Log photo as AFTER uploaded by CLEANER
                PhotosLog.objects.create(
                    booking=booking,
                    photo_url=photo_url,
                    photo_type='AFTER',
                    uploaded_by='CLEANER'
                )
                
                # 2. Update booking status to COMPLETED
                booking.status = 'COMPLETED'
                booking.save()
                
                # 3. Send invoice email automatically
                try:
                    price = booking.final_quote_price if (booking.final_quote_price and booking.final_quote_price > 0) else (booking.system_estimated_price if booking.system_estimated_price else Decimal('0.00'))
                    formatted_price = f"${price:,.2f}"
                    formatted_date_time = booking.requested_date_time.strftime('%b %d, %Y, %I:%M %p')
                    doc_type = "Invoice"
                    intro = "Thank you for your business! Please find your final invoice below:"
                    
                    biz_settings = BusinessSettings.objects.first()
                    payment_link = booking.square_checkout_url
                    if not payment_link:
                        payment_link = biz_settings.square_payment_link if biz_settings else None
                        
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
                        'payment_link': payment_link,
                        'logo_url': logo_url,
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
                    
                    if django_settings.EMAIL_HOST_USER:
                        send_email_via_resend_api(subject, text_content, html_content, booking.email)
                        print(f"Cleaner Portal: Automated invoice email sent to {booking.email} via API")
                except Exception as mail_err:
                    print(f"Cleaner Portal Email Warning: Failed to send invoice email: {mail_err}")
                    
                messages.success(request, f"Job Completed! 'After' photo uploaded, status updated to Completed, and Invoice emailed to {booking.email}.")
                return redirect('cleaner_dashboard')
            else:
                messages.error(request, "Error: Failed to upload job completion image to ImageKit. No changes were made.")
        else:
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
