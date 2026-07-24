"""
bookings/urls.py

URL Routing Architecture & Endpoint Directory for Bright Trust Janitorial Inc.

Routing Subsystems
-------------------
1. Public Website & Booking: '/', '/book/', '/success/'
2. Owner Admin Dashboard: '/dashboard/', '/dashboard/cleaners/', '/dashboard/guide/', '/dashboard/audit/'
3. JSON API Endpoints: '/api/calendar-events/', '/api/bookings/available-slots/', '/api/imagekit-auth/'
4. Cleaner Mobile Portal: '/cleaner/login/', '/cleaner/dashboard/', '/cleaner/upload-after/<pk>/'
5. External Webhooks & System Operations: '/payments/square-webhook/', '/health/'
"""

from django.urls import path
from . import views

urlpatterns = [
    # Public Marketing & Customer Booking Form Routes
    path('', views.landing_page, name='landing_page'),
    path('book/', views.booking_page, name='booking_page'),
    path('success/', views.booking_success, name='booking_success'),
    
    # Owner Admin Dashboard Routes
    path('dashboard/', views.dashboard_home, name='dashboard_home'),
    path('dashboard/login/', views.dashboard_login, name='dashboard_login'),
    path('dashboard/logout/', views.dashboard_logout, name='dashboard_logout'),
    path('dashboard/booking/add/', views.dashboard_booking_add, name='dashboard_booking_add'),
    path('dashboard/booking/edit/<int:pk>/', views.dashboard_booking_edit, name='dashboard_booking_edit'),
    path('dashboard/booking/delete/<int:pk>/', views.dashboard_booking_delete, name='dashboard_booking_delete'),
    path('dashboard/booking/email/<int:pk>/', views.dashboard_send_email, name='dashboard_send_email'),
    path('dashboard/settings/', views.dashboard_settings, name='dashboard_settings'),
    path('dashboard/settings/account/', views.dashboard_account_settings, name='dashboard_account_settings'),
    path('dashboard/audit/', views.dashboard_audit_portal, name='dashboard_audit_portal'),
    path('dashboard/audit/export/', views.dashboard_audit_export_csv, name='dashboard_audit_export_csv'),
    path('dashboard/cleaners/', views.dashboard_cleaners_list, name='dashboard_cleaners_list'),
    path('dashboard/cleaners/add/', views.dashboard_cleaner_add, name='dashboard_cleaner_add'),
    path('dashboard/cleaners/<int:pk>/edit/', views.dashboard_cleaner_edit, name='dashboard_cleaner_edit'),
    path('dashboard/guide/', views.dashboard_user_guide, name='dashboard_user_guide'),
    path('dashboard/guide/download-pdf/', views.dashboard_download_admin_pdf, name='dashboard_download_admin_pdf'),
    
    # Client-Side JSON APIs
    path('api/imagekit-auth/', views.imagekit_auth, name='imagekit_auth'),
    path('api/calendar-events/', views.calendar_events_api, name='calendar_events_api'),
    path('api/bookings/available-slots/', views.available_slots_api, name='available_slots_api'),
    path('api/test-smtp/', views.test_smtp_connection, name='test_smtp_connection'),
    path('api/test-square/', views.test_square_connection, name='test_square_connection'),
    
    # Cleaner Staff Mobile Portal Routes
    path('cleaner/login/', views.cleaner_login, name='cleaner_login'),
    path('cleaner/dashboard/', views.cleaner_dashboard, name='cleaner_dashboard'),
    path('cleaner/logout/', views.cleaner_logout, name='cleaner_logout'),
    path('cleaner/upload-after/<int:pk>/', views.cleaner_upload_after, name='cleaner_upload_after'),
    
    # Webhooks & System Health Routes
    path('payments/square-webhook/', views.square_webhook, name='square_webhook'),
    path('health/', views.health_check, name='health_check'),
]