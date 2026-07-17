from datetime import datetime, time, timedelta
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from .models import CleaningLead

def get_scheduling_config():
    """
    Get scheduling configuration values from settings, with fallbacks.
    """
    return {
        'SERVICE_DURATION_HOURS': getattr(settings, 'SERVICE_DURATION_HOURS', 4),
        'BOOKING_SLOT_INTERVAL_MINUTES': getattr(settings, 'BOOKING_SLOT_INTERVAL_MINUTES', 60),
        'MAX_CONCURRENT_CREWS': getattr(settings, 'MAX_CONCURRENT_CREWS', 1),
    }

def get_available_slots_for_date(selected_date):
    """
    Generates a list of available HH:MM strings for a given date object.
    Matches operational rule: 24/7 coverage.
    """
    config = get_scheduling_config()
    default_duration = config['SERVICE_DURATION_HOURS']
    interval_mins = config['BOOKING_SLOT_INTERVAL_MINUTES']
    max_crews = config['MAX_CONCURRENT_CREWS']
    
    tz = timezone.get_current_timezone()
    start_of_day = timezone.make_aware(datetime.combine(selected_date, time.min), tz)
    end_of_day = timezone.make_aware(datetime.combine(selected_date, time.max), tz)
    
    # Query active bookings that could overlap with any time on the selected date.
    # Active statuses: CONFIRMED, SCHEDULED, IN_PROGRESS
    active_statuses = ['CONFIRMED', 'SCHEDULED', 'IN_PROGRESS']
    
    # An existing booking overlaps with this day if it starts before end_of_day and ends after start_of_day.
    existing_bookings = CleaningLead.objects.filter(
        status__in=active_statuses,
        requested_date_time__lt=end_of_day,
        requested_end_time__gt=start_of_day
    )
    
    available_slots = []
    
    # Generate slots for the full 24 hours in intervals
    current_time = start_of_day
    while current_time < end_of_day:
        slot_start = current_time
        slot_end = current_time + timedelta(hours=default_duration)
        
        # Count overlapping active bookings
        # Conflict rule: slot_start < booking_end AND slot_end > booking_start
        overlapping_count = 0
        for booking in existing_bookings:
            eb_start = booking.requested_date_time
            eb_end = booking.requested_end_time
            
            # Check overlap range (overlap exists if slot starts before booking ends and ends after booking starts)
            if slot_start < eb_end and slot_end > eb_start:
                overlapping_count += 1
                
        if overlapping_count < max_crews:
            available_slots.append(slot_start.strftime('%H:%M'))
            
        current_time += timedelta(minutes=interval_mins)
        
    return available_slots

def check_and_reserve_slot(lead):
    """
    Validates availability of a slot for a specific booking lead.
    Utilizes select_for_update() to prevent race conditions on query phase,
    while database-level exclusion constraint serves as ultimate safety net.
    """
    config = get_scheduling_config()
    duration_hours = lead.service_duration_hours or config['SERVICE_DURATION_HOURS']
    max_crews = config['MAX_CONCURRENT_CREWS']
    
    if not lead.requested_date_time:
        return False
        
    slot_start = lead.requested_date_time
    slot_end = slot_start + timedelta(hours=duration_hours)
    
    # Update lead instance fields
    lead.requested_end_time = slot_end
    
    active_statuses = ['CONFIRMED', 'SCHEDULED', 'IN_PROGRESS']
    
    with transaction.atomic():
        # lock overlapping active bookings to optimize check stage
        existing_bookings = CleaningLead.objects.select_for_update().filter(
            status__in=active_statuses,
            requested_date_time__lt=slot_end,
            requested_end_time__gt=slot_start
        )
        
        overlapping_count = 0
        for booking in existing_bookings:
            # Self-conflict check: Exclude own row if editing
            if lead.pk and booking.pk == lead.pk:
                continue
            
            eb_start = booking.requested_date_time
            eb_end = booking.requested_end_time
            
            if slot_start < eb_end and slot_end > eb_start:
                overlapping_count += 1
                
        if overlapping_count >= max_crews:
            return False
            
        lead.save()
        return True
