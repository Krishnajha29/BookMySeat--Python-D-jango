import uuid
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.contrib import messages
from django.http import HttpResponseForbidden
from .models import Movie, Theater, Seat, Booking

def movie_list(request):
    search_query = request.GET.get('search', '').strip()
    genre_filter = request.GET.get('genre', '').strip()
    language_filter = request.GET.get('language', '').strip()

    movies = Movie.objects.all()

    if search_query:
        movies = movies.filter(name__icontains=search_query)
    if genre_filter:
        movies = movies.filter(genre__iexact=genre_filter)
    if language_filter:
        movies = movies.filter(language__iexact=language_filter)

    # Unique categories for filter badges/dropdowns
    all_genres = Movie.objects.values_list('genre', flat=True).distinct()
    all_genres = [g for g in all_genres if g]
    all_languages = Movie.objects.values_list('language', flat=True).distinct()
    all_languages = [l for l in all_languages if l]

    return render(request, 'movies/movie_list.html', {
        'movies': movies,
        'search_query': search_query,
        'selected_genre': genre_filter,
        'selected_language': language_filter,
        'all_genres': all_genres,
        'all_languages': all_languages,
    })

def movie_detail(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    theaters = Theater.objects.filter(movie=movie).order_by('time')
    return render(request, 'movies/movie_detail.html', {
        'movie': movie,
        'theaters': theaters,
    })

def theater_list(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    theaters = Theater.objects.filter(movie=movie).order_by('time')
    return render(request, 'movies/theater_list.html', {
        'movie': movie,
        'theaters': theaters,
    })

def ensure_theater_seats(theater):
    """Auto-populates standard seats if theater has none, guaranteeing working bookings."""
    if not theater.seats.exists():
        seat_objects = []
        rows = [('A', 'VIP'), ('B', 'Premium'), ('C', 'Standard')]
        for row_letter, s_type in rows:
            for num in range(1, 11):
                seat_objects.append(Seat(
                    theater=theater,
                    seat_number=f'{row_letter}{num}',
                    seat_type=s_type,
                    is_booked=False
                ))
        Seat.objects.bulk_create(seat_objects)

@login_required(login_url='/login/')
def book_seats(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    ensure_theater_seats(theater)
    seats = Seat.objects.filter(theater=theater).order_by('seat_number')

    if request.method == 'POST':
        selected_seat_ids = request.POST.getlist('seats')
        if not selected_seat_ids:
            messages.error(request, "Please select at least one seat to proceed.")
            return render(request, "movies/seat_selection.html", {
                'theaters': theater,
                'seats': seats,
                'error': "Please select at least one seat."
            })

        # Validate seats belong to this theater and are not booked
        selected_seats = Seat.objects.filter(id__in=selected_seat_ids, theater=theater)
        already_booked = selected_seats.filter(is_booked=True)

        if already_booked.exists():
            booked_names = ', '.join([s.seat_number for s in already_booked])
            messages.error(request, f"Sorry, the following seats are already booked: {booked_names}")
            return render(request, "movies/seat_selection.html", {
                'theaters': theater,
                'seats': seats,
                'error': f"Seats already booked: {booked_names}"
            })

        # Store selected seats in session and proceed to Booking Summary
        request.session['selected_seat_ids'] = [s.id for s in selected_seats]
        request.session['booking_theater_id'] = theater.id

        return redirect('booking_summary', theater_id=theater.id)

    return render(request, 'movies/seat_selection.html', {
        'theaters': theater,
        'seats': seats
    })

@login_required(login_url='/login/')
def booking_summary(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    selected_seat_ids = request.session.get('selected_seat_ids', [])

    if not selected_seat_ids or request.session.get('booking_theater_id') != theater.id:
        messages.warning(request, "No seats selected. Please select seats first.")
        return redirect('book_seats', theater_id=theater.id)

    selected_seats = Seat.objects.filter(id__in=selected_seat_ids, theater=theater)

    # Re-verify availability
    if selected_seats.filter(is_booked=True).exists():
        messages.error(request, "One or more of your selected seats have been booked. Please choose again.")
        return redirect('book_seats', theater_id=theater.id)

    ticket_subtotal = sum(s.price for s in selected_seats)
    convenience_fee = Decimal(len(selected_seats)) * Decimal('15.00')
    gst = (convenience_fee * Decimal('0.18')).quantize(Decimal('0.01'))
    grand_total = ticket_subtotal + convenience_fee + gst

    request.session['grand_total'] = str(grand_total)

    return render(request, 'movies/booking_summary.html', {
        'theater': theater,
        'movie': theater.movie,
        'selected_seats': selected_seats,
        'ticket_subtotal': ticket_subtotal,
        'convenience_fee': convenience_fee,
        'gst': gst,
        'grand_total': grand_total,
    })

@login_required(login_url='/login/')
def payment_process(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    selected_seat_ids = request.session.get('selected_seat_ids', [])
    grand_total_str = request.session.get('grand_total')

    if not selected_seat_ids or not grand_total_str:
        messages.warning(request, "Your booking session has expired. Please select seats again.")
        return redirect('book_seats', theater_id=theater.id)

    grand_total = Decimal(grand_total_str)
    selected_seats = Seat.objects.filter(id__in=selected_seat_ids, theater=theater)

    if request.method == 'POST':
        action = request.POST.get('action', 'pay')
        payment_method = request.POST.get('payment_method', 'Credit/Debit Card')

        if action == 'fail':
            messages.error(request, "Payment was declined or cancelled in simulation mode. You can try again.")
            return render(request, 'movies/payment_simulation.html', {
                'theater': theater,
                'movie': theater.movie,
                'selected_seats': selected_seats,
                'grand_total': grand_total,
                'payment_failed': True,
            })

        # Process payment with atomic transaction and row locking
        try:
            with transaction.atomic():
                # Lock the seats to prevent race conditions / duplicate booking
                locked_seats = list(Seat.objects.select_for_update().filter(id__in=selected_seat_ids, theater=theater))

                # Check if any seat became booked concurrently
                already_booked = [s.seat_number for s in locked_seats if s.is_booked]
                if already_booked:
                    messages.error(request, f"Sorry! Seats {', '.join(already_booked)} were just booked by another user.")
                    return redirect('book_seats', theater_id=theater.id)

                booking_reference = f"BMS-{uuid.uuid4().hex[:8].upper()}"
                per_seat_amount = (grand_total / Decimal(len(locked_seats))).quantize(Decimal('0.01'))

                for seat in locked_seats:
                    Booking.objects.create(
                        user=request.user,
                        seat=seat,
                        movie=theater.movie,
                        theater=theater,
                        booking_reference=booking_reference,
                        total_amount=per_seat_amount,
                        payment_status='Completed',
                        payment_method=payment_method
                    )
                    seat.is_booked = True
                    seat.save()

                # Clean up session
                request.session.pop('selected_seat_ids', None)
                request.session.pop('booking_theater_id', None)
                request.session.pop('grand_total', None)

                messages.success(request, f"Booking confirmed! Reference: {booking_reference}")
                return redirect('booking_confirmation', booking_reference=booking_reference)

        except IntegrityError:
            messages.error(request, "A database conflict occurred while finalizing your booking. Please try again.")
            return redirect('book_seats', theater_id=theater.id)

    return render(request, 'movies/payment_simulation.html', {
        'theater': theater,
        'movie': theater.movie,
        'selected_seats': selected_seats,
        'grand_total': grand_total,
        'payment_failed': False,
    })

@login_required(login_url='/login/')
def booking_confirmation(request, booking_reference):
    bookings = Booking.objects.filter(booking_reference=booking_reference)
    if not bookings.exists():
        messages.error(request, "Booking not found.")
        return redirect('profile')

    first_booking = bookings.first()
    # Authorization check: only booking owner or staff can view
    if first_booking.user != request.user and not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to view this booking.")

    seats = [b.seat for b in bookings]
    total_paid = sum(b.total_amount for b in bookings)

    return render(request, 'movies/booking_confirmation.html', {
        'booking_reference': booking_reference,
        'bookings': bookings,
        'first_booking': first_booking,
        'movie': first_booking.movie,
        'theater': first_booking.theater,
        'seats': seats,
        'total_paid': total_paid,
    })

@login_required(login_url='/login/')
def cancel_booking(request, booking_reference):
    if request.method == 'POST':
        bookings = Booking.objects.filter(booking_reference=booking_reference, user=request.user)
        if not bookings.exists():
            messages.error(request, "Booking not found or not authorized.")
            return redirect('profile')

        with transaction.atomic():
            for b in bookings:
                b.payment_status = 'Cancelled'
                b.save()
                seat = b.seat
                seat.is_booked = False
                seat.save()

        messages.success(request, f"Booking {booking_reference} has been successfully cancelled and seats released.")
    return redirect('profile')
