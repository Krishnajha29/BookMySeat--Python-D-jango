from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from .forms import UserRegisterForm, UserUpdateForm
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from movies.models import Movie, Booking

def home(request):
    movies = Movie.objects.all()
    return render(request, 'home.html', {'movies': movies})

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            login(request, user)
            messages.success(request, f'Welcome to BookMySeat, {username}! Your account has been created.')
            return redirect('profile')
        else:
            messages.error(request, 'Registration failed. Please correct the errors below.')
    else:
        form = UserRegisterForm()
    return render(request, 'users/register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f'Welcome back, {user.username}!')
            next_url = request.GET.get('next', '/')
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
    else:
        form = AuthenticationForm()
    return render(request, 'users/login.html', {'form': form})

@login_required
def profile(request):
    user_bookings = Booking.objects.filter(user=request.user).order_by('-booked_at')

    # Group bookings by booking reference for a clean order summary
    grouped_bookings = {}
    for b in user_bookings:
        ref = b.booking_reference or f"LEGACY-{b.id}"
        if ref not in grouped_bookings:
            grouped_bookings[ref] = {
                'reference': ref,
                'movie': b.movie,
                'theater': b.theater,
                'booked_at': b.booked_at,
                'payment_status': b.payment_status,
                'payment_method': b.payment_method,
                'seats': [b.seat.seat_number],
                'total_amount': b.total_amount,
                'can_cancel': b.payment_status == 'Completed',
            }
        else:
            grouped_bookings[ref]['seats'].append(b.seat.seat_number)
            grouped_bookings[ref]['total_amount'] += b.total_amount

    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        if u_form.is_valid():
            u_form.save()
            messages.success(request, 'Your profile details have been updated successfully.')
            return redirect('profile')
        else:
            messages.error(request, 'Please correct the errors in the profile form.')
    else:
        u_form = UserUpdateForm(instance=request.user)

    return render(request, 'users/profile.html', {
        'u_form': u_form,
        'bookings': user_bookings, # Backwards compatibility
        'grouped_bookings': list(grouped_bookings.values()),
    })

@login_required
def reset_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Password changed successfully! Please log in with your new password.')
            return redirect('login')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PasswordChangeForm(user=request.user)
    return render(request, 'users/reset_password.html', {'form': form})