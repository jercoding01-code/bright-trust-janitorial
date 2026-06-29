from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing_page, name='landing_page'),
    path('book/', views.booking_page, name='booking_page'),
    path('success/', views.booking_success, name='booking_success'),
]   