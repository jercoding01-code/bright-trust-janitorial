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
from datetime import timedelta
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings as django_settings
import os
import urllib.parse
import uuid
import requests

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


def booking_page(request):
    track_visit(request)
    if request.method == 'POST':
        form = CleaningLeadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                form.save()
                return redirect('booking_success')
            except Exception as e:
                print(f"Error saving lead: {e}")
    else:
        form = CleaningLeadForm()
    return render(request, 'booking.html', {'form': form})


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
            form.save()
            messages.success(request, "New booking successfully added.")
            return redirect('dashboard_home')
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
            form.save()
            messages.success(request, f"Booking for {lead.first_name} {lead.last_name} updated successfully.")
            return redirect('dashboard_home')
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
        "quick_pay": {
            "name": f"25% Downpayment: Clean Lead #{lead.pk}",
            "price_money": {
                "amount": amount_cents,
                "currency": "CAD"
            },
            "location_id": location_id
        },
        "checkout_options": {
            "redirect_url": "https://bright-trust-janitorial.onrender.com/success/"
        },
        "reference_id": str(lead.pk)
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

    context = {
        'lead': lead,
        'doc_type': doc_type,
        'intro': intro,
        'formatted_price': formatted_price,
        'formatted_date_time': formatted_date_time,
        'payment_link': payment_link,
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
            msg = EmailMultiAlternatives(subject, text_content, django_settings.DEFAULT_FROM_EMAIL, [lead.email])
            
            # Embed logo
            logo_path = os.path.join(django_settings.BASE_DIR, 'static', 'images', 'logo.JPEG')
            if os.path.exists(logo_path):
                from email.mime.image import MIMEImage
                with open(logo_path, 'rb') as f:
                    logo_img = MIMEImage(f.read())
                    logo_img.add_header('Content-ID', '<logo_image>')
                    logo_img.add_header('Content-Disposition', 'inline', filename='logo.JPEG')
                    msg.attach(logo_img)
            
            msg.attach_alternative(html_content, "text/html")
            msg.send()
            
            if lead.status == 'NEW':
                lead.status = 'CONTACTED'
                lead.save()
                
            email_sent_successfully = True
            messages.success(request, f"HTML Email successfully sent to {lead.email} via server.")
        except Exception as e:
            messages.error(request, f"Server SMTP Email failed: {e}. You can use the fallback mailto link below.")
    else:
        if lead.status == 'NEW':
            lead.status = 'CONTACTED'
            lead.save()
        messages.info(request, "Server SMTP is not configured. Please use the mailto link below.")

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
from django.http import HttpResponse
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
                    lead_id = int(reference_id)
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
