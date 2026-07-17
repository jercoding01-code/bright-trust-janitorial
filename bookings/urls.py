from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing_page, name='landing_page'),
    path('book/', views.booking_page, name='booking_page'),
    path('success/', views.booking_success, name='booking_success'),
    
    # Dashboard routes
    path('dashboard/', views.dashboard_home, name='dashboard_home'),
    path('dashboard/login/', views.dashboard_login, name='dashboard_login'),
    path('dashboard/logout/', views.dashboard_logout, name='dashboard_logout'),
    path('dashboard/booking/add/', views.dashboard_booking_add, name='dashboard_booking_add'),
    path('dashboard/booking/edit/<int:pk>/', views.dashboard_booking_edit, name='dashboard_booking_edit'),
    path('dashboard/booking/email/<int:pk>/', views.dashboard_send_email, name='dashboard_send_email'),
    path('dashboard/settings/', views.dashboard_settings, name='dashboard_settings'),
    path('dashboard/settings/account/', views.dashboard_account_settings, name='dashboard_account_settings'),
    path('api/imagekit-auth/', views.imagekit_auth, name='imagekit_auth'),
    path('api/calendar-events/', views.calendar_events_api, name='calendar_events_api'),
    path('api/bookings/available-slots/', views.available_slots_api, name='available_slots_api'),
    path('cleaner/login/', views.cleaner_login, name='cleaner_login'),
    path('cleaner/dashboard/', views.cleaner_dashboard, name='cleaner_dashboard'),
    path('cleaner/logout/', views.cleaner_logout, name='cleaner_logout'),
    path('cleaner/upload-after/<int:pk>/', views.cleaner_upload_after, name='cleaner_upload_after'),
    path('payments/square-webhook/', views.square_webhook, name='square_webhook'),
]