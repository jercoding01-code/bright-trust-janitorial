from django.shortcuts import redirect, render
from .forms import CleaningLeadForm # Ensure you import your form


def landing_page(request):
    return render(request, 'index.html')

def booking_page(request):
    if request.method == 'POST':
        form = CleaningLeadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                form.save()
                return redirect('booking_success')  # Redirecting to a success URL
            except Exception as e:
                # Log the error here for the developer to see
                print(f"Error saving lead: {e}")
    else:
        form = CleaningLeadForm()
    return render(request, 'booking.html', {'form': form})

# Add this new function for the success page
def booking_success(request):
    return render(request, 'success.html')
def calculate_quote(sqft):
    # Base pay of $95.00 + $0.65 per square foot
    base_pay = 95.00
    variable_rate = 0.65
    
    price = base_pay + (float(sqft) * variable_rate)
    
    return round(price, 2)
