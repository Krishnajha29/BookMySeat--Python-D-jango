import io
import json
import uuid
import hmac
import hashlib
from decimal import Decimal
from datetime import datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction, IntegrityError
from django.db.models import Count, Min, Max, Avg, Q
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from django.conf import settings

from .models import Movie, Theater, Seat, Booking, Review, MoviePoster, MovieViewHistory
from .tickets import generate_ticket_pdf, verify_ticket_token, generate_ticket_token
from .tasks import send_ticket_email_async, release_expired_seat_holds
from .analytics import get_business_analytics, generate_analytics_csv_buffer

RESERVATION_HOLD_MINUTES = 2


# ==============================================================================
# REQUIREMENT 1: MOVIE DISCOVERY, SEARCH, FILTERS & RECOMMENDATIONS
# ==============================================================================

def movie_list(request):
    """Movie discovery with multi-criteria filtering, dynamic counts, sorting, pagination & recommendations."""
    # Run periodic cleanup of expired seat holds
    release_expired_seat_holds()

    search_query = request.GET.get('search', '').strip()
    genre_filter = request.GET.get('genre', '').strip()
    language_filter = request.GET.get('language', '').strip()
    city_filter = request.GET.get('city', '').strip()
    theatre_filter = request.GET.get('theatre', '').strip()
    rating_filter = request.GET.get('rating', '').strip()
    sort_by = request.GET.get('sort', 'popularity').strip()

    # Base Queryset with prefetch for optimization
    movies_qs = Movie.objects.all().prefetch_related('theaters')
    total_unfiltered_count = Movie.objects.count()

    # Search by Title, Cast, or Description
    if search_query:
        movies_qs = movies_qs.filter(
            Q(name__icontains=search_query) |
            Q(cast__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # Filters
    if genre_filter:
        movies_qs = movies_qs.filter(genre__iexact=genre_filter)
    if language_filter:
        movies_qs = movies_qs.filter(language__iexact=language_filter)
    if city_filter:
        movies_qs = movies_qs.filter(theaters__city__iexact=city_filter).distinct()
    if theatre_filter:
        movies_qs = movies_qs.filter(theaters__name__icontains=theatre_filter).distinct()
    if rating_filter:
        try:
            movies_qs = movies_qs.filter(rating__gte=float(rating_filter))
        except ValueError:
            pass

    # Sorting options
    if sort_by == 'popularity':
        # Popularity defined as total completed bookings count
        movies_qs = movies_qs.annotate(
            booking_count=Count('booking', filter=Q(booking__payment_status='Completed'))
        ).order_by('-booking_count', '-rating')
    elif sort_by == 'newest':
        movies_qs = movies_qs.order_by('-release_date', '-id')
    elif sort_by == 'rating':
        movies_qs = movies_qs.order_by('-rating')
    elif sort_by == 'price_low':
        movies_qs = movies_qs.annotate(min_price=Min('theaters__price')).order_by('min_price')
    elif sort_by == 'price_high':
        movies_qs = movies_qs.annotate(max_price=Max('theaters__price')).order_by('-max_price')
    else:
        movies_qs = movies_qs.order_by('-id')

    # Result count for filtered queryset
    result_count = movies_qs.count()

    # Pagination: 8 movies per page
    paginator = Paginator(movies_qs, 8)
    page = request.GET.get('page', 1)
    try:
        movies_page = paginator.page(page)
    except PageNotAnInteger:
        movies_page = paginator.page(1)
    except EmptyPage:
        movies_page = paginator.page(paginator.num_pages)

    # Personalized Recommendations (displayed on primary discovery page when no search/filter is active)
    recommended_movies = []
    has_active_filters = any([search_query, genre_filter, language_filter, city_filter, theatre_filter, rating_filter])
    if not has_active_filters:
        if request.user.is_authenticated:
            # Based on user's booking history and viewed genres
            booked_genres = list(Booking.objects.filter(user=request.user).values_list('movie__genre', flat=True).distinct())
            viewed_genres = list(MovieViewHistory.objects.filter(user=request.user).values_list('movie__genre', flat=True).distinct())
            preferred_genres = list(set(filter(None, booked_genres + viewed_genres)))

            if preferred_genres:
                recommended_movies = (
                    Movie.objects.filter(genre__in=preferred_genres)
                    .exclude(id__in=Booking.objects.filter(user=request.user).values_list('movie_id', flat=True))
                    .order_by('-rating')[:4]
                )

        # Fallback recommendations if user has no history or is anonymous
        if not recommended_movies:
            recommended_movies = Movie.objects.order_by('-rating')[:4]

    # Distinct categories for filter dropdowns/badges
    all_genres = list(filter(None, Movie.objects.values_list('genre', flat=True).distinct()))
    all_languages = list(filter(None, Movie.objects.values_list('language', flat=True).distinct()))
    all_cities = list(filter(None, Theater.objects.values_list('city', flat=True).distinct()))

    return render(request, 'movies/movie_list.html', {
        'movies': movies_page,
        'result_count': result_count,
        'total_unfiltered_count': total_unfiltered_count,
        'search_query': search_query,
        'selected_genre': genre_filter,
        'selected_language': language_filter,
        'selected_city': city_filter,
        'selected_theatre': theatre_filter,
        'selected_rating': rating_filter,
        'selected_sort': sort_by,
        'all_genres': all_genres,
        'all_languages': all_languages,
        'all_cities': all_cities,
        'recommended_movies': recommended_movies,
    })


# ==============================================================================
# REQUIREMENT 3: MOVIE DETAILS, TRAILERS, REVIEWS & RATINGS
# ==============================================================================

def movie_detail(request, movie_id):
    """Detailed movie page with YouTube trailer, verified reviews, similar & trending recommendations."""
    movie = get_object_or_404(Movie, id=movie_id)
    theaters = Theater.objects.filter(movie=movie).order_by('time')

    # Record viewing history for authenticated users
    if request.user.is_authenticated:
        MovieViewHistory.objects.update_or_create(user=request.user, movie=movie)

    # Active Reviews
    reviews = movie.reviews.filter(is_hidden=False).select_related('user').order_by('-created_at')

    # Verified reviewer eligibility check
    user_can_review = False
    existing_user_review = None
    if request.user.is_authenticated:
        has_completed_booking = Booking.objects.filter(
            user=request.user,
            movie=movie,
            payment_status='Completed'
        ).exists()
        user_can_review = has_completed_booking
        existing_user_review = movie.reviews.filter(user=request.user).first()

    # Similar movies (matching genre or language)
    similar_movies = (
        Movie.objects.filter(Q(genre=movie.genre) | Q(language=movie.language))
        .exclude(id=movie.id)
        .order_by('-rating')[:4]
    )

    # Trending movies based on booking counts
    trending_movies = (
        Movie.objects.exclude(id=movie.id)
        .annotate(bookings_count=Count('booking', filter=Q(booking__payment_status='Completed')))
        .order_by('-bookings_count')[:4]
    )

    return render(request, 'movies/movie_detail.html', {
        'movie': movie,
        'theaters': theaters,
        'reviews': reviews,
        'user_can_review': user_can_review,
        'existing_user_review': existing_user_review,
        'similar_movies': similar_movies,
        'trending_movies': trending_movies,
        'trailer_embed_url': movie.get_youtube_embed_url(),
    })

@login_required(login_url='/login/')
def submit_or_edit_review(request, movie_id):
    """Allows verified viewers to submit or edit their movie review."""
    movie = get_object_or_404(Movie, id=movie_id)

    # Verify eligibility: completed booking required
    has_booked = Booking.objects.filter(
        user=request.user,
        movie=movie,
        payment_status='Completed'
    ).exists()

    if not has_booked and not request.user.is_staff:
        messages.error(request, "Only viewers with confirmed bookings can review this movie.")
        return redirect('movie_detail', movie_id=movie.id)

    if request.method == 'POST':
        try:
            rating_val = int(request.POST.get('rating', 10))
            rating_val = max(1, min(10, rating_val))
        except ValueError:
            rating_val = 10

        comment = request.POST.get('comment', '').strip()
        if not comment:
            messages.error(request, "Please enter review comments.")
            return redirect('movie_detail', movie_id=movie.id)

        review, created = Review.objects.update_or_create(
            movie=movie,
            user=request.user,
            defaults={
                'rating': rating_val,
                'comment': comment,
                'is_verified_viewer': True,
                'is_hidden': False,
            }
        )
        movie.update_average_rating()
        messages.success(request, "Your review has been published!" if created else "Your review has been updated!")

    return redirect('movie_detail', movie_id=movie.id)

@login_required(login_url='/login/')
def report_review(request, review_id):
    """Allows users to report inappropriate reviews for administrative moderation."""
    review = get_object_or_404(Review, id=review_id)
    if request.method == 'POST':
        reason = request.POST.get('reason', 'Inappropriate or offensive content').strip()
        review.is_reported = True
        review.report_reason = reason
        review.save(update_fields=['is_reported', 'report_reason'])
        messages.info(request, "Thank you. This review has been flagged for administrative moderation.")
    return redirect('movie_detail', movie_id=review.movie.id)


# ==============================================================================
# REQUIREMENT 5: LIVE SEAT AVAILABILITY & TWO-MINUTE RESERVATIONS
# ==============================================================================

def theater_list(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    theaters = Theater.objects.filter(movie=movie).order_by('time')
    return render(request, 'movies/theater_list.html', {
        'movie': movie,
        'theaters': theaters,
    })

def ensure_theater_seats(theater):
    """Guarantees standard seats exist for seamless booking testing."""
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
    """Interactive seat selection with live 4-state availability and 2-minute hold creation."""
    theater = get_object_or_404(Theater, id=theater_id)
    ensure_theater_seats(theater)

    # Release any expired holds across this theater
    now = timezone.now()
    Seat.objects.filter(
        theater=theater,
        is_booked=False,
        reserved_until__isnull=False,
        reserved_until__lte=now
    ).update(reserved_until=None, reserved_by=None)

    seats = Seat.objects.filter(theater=theater).order_by('seat_number')

    if request.method == 'POST':
        selected_seat_ids = request.POST.getlist('seats')
        if not selected_seat_ids:
            messages.error(request, "Please select at least one seat to proceed.")
            return render(request, "movies/seat_selection.html", {'theaters': theater, 'seats': seats})

        # Atomic transaction and row-level locking
        with transaction.atomic():
            locked_seats = list(Seat.objects.select_for_update().filter(id__in=selected_seat_ids, theater=theater))

            # Validate availability against booked and active third-party holds
            unavailable_seats = []
            for s in locked_seats:
                if s.is_booked:
                    unavailable_seats.append(f"{s.seat_number} (Sold)")
                elif s.reserved_until and s.reserved_until > now and s.reserved_by_id != request.user.id:
                    unavailable_seats.append(f"{s.seat_number} (Reserved by another user)")

            if unavailable_seats:
                messages.error(request, f"Unavailable: {', '.join(unavailable_seats)}. Please select different seats.")
                return render(request, "movies/seat_selection.html", {'theaters': theater, 'seats': seats})

            # Release any previous holds held by this user on other seats in this theatre
            Seat.objects.filter(theater=theater, reserved_by=request.user, is_booked=False).exclude(id__in=selected_seat_ids).update(
                reserved_until=None,
                reserved_by=None
            )

            # Create 2-minute hold window
            hold_expiry = now + timedelta(minutes=RESERVATION_HOLD_MINUTES)
            for s in locked_seats:
                s.reserved_until = hold_expiry
                s.reserved_by = request.user
                s.save(update_fields=['reserved_until', 'reserved_by'])

            # Store in session
            request.session['selected_seat_ids'] = [s.id for s in locked_seats]
            request.session['booking_theater_id'] = theater.id
            request.session['hold_expires_at'] = hold_expiry.isoformat()

            return redirect('booking_summary', theater_id=theater.id)

    # Attach dynamic user-specific status for template rendering
    seat_status_list = []
    for s in seats:
        status = s.get_status_for_user(request.user)
        seat_status_list.append({
            'id': s.id,
            'number': s.seat_number,
            'type': s.seat_type,
            'price': float(s.price),
            'status': status,
            'isBooked': (status == 'booked'),
            'isReserved': (status == 'reserved'),
        })

    return render(request, 'movies/seat_selection.html', {
        'theaters': theater,
        'seats': seats,
        'seat_status_json': json.dumps(seat_status_list),
    })

@login_required(login_url='/login/')
def booking_summary(request, theater_id):
    """Booking summary enforcing active 2-minute hold validation before payment transition."""
    theater = get_object_or_404(Theater, id=theater_id)
    selected_seat_ids = request.session.get('selected_seat_ids', [])
    hold_expires_iso = request.session.get('hold_expires_at')

    if not selected_seat_ids or not hold_expires_iso or request.session.get('booking_theater_id') != theater.id:
        messages.warning(request, "Your booking session expired. Please select your seats again.")
        return redirect('book_seats', theater_id=theater.id)

    now = timezone.now()
    hold_expires = datetime.fromisoformat(hold_expires_iso)
    if hold_expires <= now:
        messages.error(request, "Your 2-minute reservation hold has expired. Seats were released.")
        return redirect('book_seats', theater_id=theater.id)

    remaining_seconds = max(0, int((hold_expires - now).total_seconds()))

    selected_seats = Seat.objects.filter(
        id__in=selected_seat_ids,
        theater=theater,
        reserved_by=request.user,
        is_booked=False
    )

    if selected_seats.count() != len(selected_seat_ids):
        messages.error(request, "One or more seats are no longer reserved. Please select seats again.")
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
        'remaining_seconds': remaining_seconds,
    })


# ==============================================================================
# REQUIREMENT 4: PAYMENT INTEGRATION & WEBHOOK VERIFICATION
# ==============================================================================

@login_required(login_url='/login/')
def payment_process(request, theater_id):
    """Server-side payment processing supporting simulated modes and verified confirmation."""
    theater = get_object_or_404(Theater, id=theater_id)
    selected_seat_ids = request.session.get('selected_seat_ids', [])
    grand_total_str = request.session.get('grand_total')
    hold_expires_iso = request.session.get('hold_expires_at')

    if not selected_seat_ids or not grand_total_str or not hold_expires_iso:
        messages.warning(request, "Booking session expired.")
        return redirect('book_seats', theater_id=theater.id)

    now = timezone.now()
    hold_expires = datetime.fromisoformat(hold_expires_iso)
    if hold_expires <= now:
        messages.error(request, "Reservation window expired before payment was completed.")
        return redirect('book_seats', theater_id=theater.id)

    grand_total = Decimal(grand_total_str)
    selected_seats = Seat.objects.filter(id__in=selected_seat_ids, theater=theater)
    remaining_seconds = max(0, int((hold_expires - now).total_seconds()))

    if request.method == 'POST':
        action = request.POST.get('action', 'pay')
        payment_method = request.POST.get('payment_method', 'Credit/Debit Card')

        # Handle Simulated Failure
        if action == 'fail':
            messages.error(request, "Payment was declined or cancelled in sandbox simulation.")
            return render(request, 'movies/payment_simulation.html', {
                'theater': theater,
                'movie': theater.movie,
                'selected_seats': selected_seats,
                'grand_total': grand_total,
                'remaining_seconds': remaining_seconds,
                'payment_failed': True,
            })

        # Process Verified Payment with atomic locking
        try:
            with transaction.atomic():
                locked_seats = list(Seat.objects.select_for_update().filter(id__in=selected_seat_ids, theater=theater))

                # Double check against concurrent bookings
                already_booked = [s.seat_number for s in locked_seats if s.is_booked]
                if already_booked:
                    messages.error(request, f"Seats {', '.join(already_booked)} are already booked.")
                    return redirect('book_seats', theater_id=theater.id)

                booking_reference = f"BMS-{uuid.uuid4().hex[:8].upper()}"
                per_seat_amount = (grand_total / Decimal(len(locked_seats))).quantize(Decimal('0.01'))
                gateway_order = f"order_{uuid.uuid4().hex[:12]}"
                gateway_payment = f"pay_{uuid.uuid4().hex[:12]}"

                for seat in locked_seats:
                    Booking.objects.create(
                        user=request.user,
                        seat=seat,
                        movie=theater.movie,
                        theater=theater,
                        booking_reference=booking_reference,
                        total_amount=per_seat_amount,
                        payment_status='Completed',
                        payment_method=payment_method,
                        gateway_order_id=gateway_order,
                        gateway_payment_id=gateway_payment,
                    )
                    seat.is_booked = True
                    seat.reserved_until = None
                    seat.reserved_by = None
                    seat.save(update_fields=['is_booked', 'reserved_until', 'reserved_by'])

                # Dispatch Celery background PDF ticket & email task after DB commit
                user_email = request.user.email or "tickets@bookmyseat.com"
                transaction.on_commit(lambda: send_ticket_email_async.delay(booking_reference, user_email))

                # Clean up session
                request.session.pop('selected_seat_ids', None)
                request.session.pop('booking_theater_id', None)
                request.session.pop('grand_total', None)
                request.session.pop('hold_expires_at', None)

                messages.success(request, f"Booking confirmed! E-Ticket generated for {booking_reference}")
                return redirect('booking_confirmation', booking_reference=booking_reference)

        except IntegrityError:
            messages.error(request, "Database conflict during booking. Please try again.")
            return redirect('book_seats', theater_id=theater.id)

    return render(request, 'movies/payment_simulation.html', {
        'theater': theater,
        'movie': theater.movie,
        'selected_seats': selected_seats,
        'grand_total': grand_total,
        'remaining_seconds': remaining_seconds,
        'payment_failed': False,
        'razorpay_key': getattr(settings, 'RAZORPAY_KEY_ID', 'rzp_test_bookmyseat_demo'),
    })

@csrf_exempt
def payment_webhook(request):
    """Verifies gateway webhook signatures and idempotently updates payment/booking status."""
    if request.method != 'POST':
        return HttpResponse("Method Not Allowed", status=405)

    signature = request.headers.get('X-Razorpay-Signature') or request.META.get('HTTP_X_RAZORPAY_SIGNATURE', '')
    webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', 'test_webhook_secret_demo').encode('utf-8')
    raw_body = request.body

    # Verify HMAC-SHA256 signature
    generated_sig = hmac.new(webhook_secret, raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(generated_sig, signature):
        return HttpResponseForbidden("Invalid webhook signature")

    try:
        data = json.loads(raw_body.decode('utf-8'))
        event = data.get('event')
        payload = data.get('payload', {}).get('payment', {}).get('entity', {})
        order_id = payload.get('order_id')
        payment_id = payload.get('id')

        if order_id:
            bookings = Booking.objects.filter(gateway_order_id=order_id)
            if event == 'payment.captured':
                # Idempotent confirmation
                bookings.filter(payment_status='Pending').update(
                    payment_status='Completed',
                    gateway_payment_id=payment_id
                )
            elif event == 'payment.failed':
                bookings.filter(payment_status='Pending').update(payment_status='Failed')
                # Release seats
                for b in bookings:
                    b.seat.is_booked = False
                    b.seat.save(update_fields=['is_booked'])

        return JsonResponse({'status': 'ok', 'processed': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


# ==============================================================================
# REQUIREMENT 2: AUTOMATED PDF TICKETS & QR VERIFICATION
# ==============================================================================

@login_required(login_url='/login/')
def booking_confirmation(request, booking_reference):
    bookings = Booking.objects.filter(booking_reference=booking_reference)
    if not bookings.exists():
        messages.error(request, "Booking not found.")
        return redirect('profile')

    first_booking = bookings.first()
    if first_booking.user != request.user and not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to view this booking.")

    seats = [b.seat for b in bookings]
    total_paid = sum(b.total_amount for b in bookings)
    token = generate_ticket_token(booking_reference)

    return render(request, 'movies/booking_confirmation.html', {
        'booking_reference': booking_reference,
        'bookings': bookings,
        'first_booking': first_booking,
        'movie': first_booking.movie,
        'theater': first_booking.theater,
        'seats': seats,
        'total_paid': total_paid,
        'verification_token': token,
    })

@login_required(login_url='/login/')
def download_ticket_pdf(request, booking_reference):
    """Generates and serves downloadable PDF ticket with authorization check."""
    bookings = Booking.objects.filter(booking_reference=booking_reference)
    if not bookings.exists():
        return HttpResponse("Booking not found", status=404)

    first_booking = bookings.first()
    if first_booking.user != request.user and not request.user.is_staff:
        return HttpResponseForbidden("You are not authorized to download this ticket.")

    pdf_bytes = generate_ticket_pdf(booking_reference)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="BookMySeat_Ticket_{booking_reference}.pdf"'
    return response

def verify_ticket_qr(request, token):
    """Server-side ticket authenticity verification via cryptographically signed QR code."""
    result = verify_ticket_token(token)
    return render(request, 'movies/ticket_verification.html', {'result': result, 'token': token})


# ==============================================================================
# REQUIREMENT 6: ADMIN DASHBOARD & BUSINESS ANALYTICS
# ==============================================================================

@user_passes_test(lambda u: u.is_staff, login_url='/login/')
def admin_dashboard(request):
    """Admin dashboard with date-range filters, multi-period revenue, occupancy, and KPIs."""
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            start_date = timezone.make_aware(start_date)
        except ValueError:
            pass
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            end_date = timezone.make_aware(end_date)
        except ValueError:
            pass

    analytics_data = get_business_analytics(start_date=start_date, end_date=end_date)
    reported_reviews = Review.objects.filter(is_reported=True).select_related('movie', 'user')

    return render(request, 'movies/admin_dashboard.html', {
        'analytics': analytics_data,
        'reported_reviews': reported_reviews,
        'start_date_str': start_date_str or analytics_data['start_date'].strftime('%Y-%m-%d'),
        'end_date_str': end_date_str or analytics_data['end_date'].strftime('%Y-%m-%d'),
    })

@user_passes_test(lambda u: u.is_staff, login_url='/login/')
def export_analytics_csv(request):
    """Exports sanitized CSV reports with formula injection protections."""
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = timezone.make_aware(datetime.strptime(start_date_str, '%Y-%m-%d'))
        except ValueError:
            pass
    if end_date_str:
        try:
            end_date = timezone.make_aware(datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59))
        except ValueError:
            pass

    analytics_data = get_business_analytics(start_date=start_date, end_date=end_date)
    csv_bytes = generate_analytics_csv_buffer(analytics_data)

    response = HttpResponse(csv_bytes, content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="BookMySeat_Analytics_{timezone.now().strftime("%Y%m%d")}.csv"'
    return response

@user_passes_test(lambda u: u.is_staff, login_url='/login/')
def moderate_review(request, review_id):
    """Administrative review moderation: hide or approve reported reviews."""
    review = get_object_or_404(Review, id=review_id)
    action = request.POST.get('action')
    if action == 'hide':
        review.is_hidden = True
        review.is_reported = False
        review.save(update_fields=['is_hidden', 'is_reported'])
        review.movie.update_average_rating()
        messages.success(request, f"Review #{review.id} has been hidden.")
    elif action == 'approve':
        review.is_reported = False
        review.is_hidden = False
        review.report_reason = None
        review.save(update_fields=['is_reported', 'is_hidden', 'report_reason'])
        review.movie.update_average_rating()
        messages.success(request, f"Review #{review.id} approved and restored.")
    return redirect('admin_dashboard')

@login_required(login_url='/login/')
def cancel_booking(request, booking_reference):
    """Allows user to cancel their booking, record simulated refund, and release seats."""
    if request.method == 'POST':
        bookings = Booking.objects.filter(booking_reference=booking_reference, user=request.user)
        if not bookings.exists():
            messages.error(request, "Booking not found or not authorized.")
            return redirect('profile')

        with transaction.atomic():
            refund_id = f"rfnd_{uuid.uuid4().hex[:10]}"
            for b in bookings:
                b.payment_status = 'Cancelled'
                b.is_refunded = True
                b.refund_amount = b.total_amount
                b.refund_id = refund_id
                b.save(update_fields=['payment_status', 'is_refunded', 'refund_amount', 'refund_id'])

                seat = b.seat
                seat.is_booked = False
                seat.reserved_until = None
                seat.reserved_by = None
                seat.save(update_fields=['is_booked', 'reserved_until', 'reserved_by'])

        messages.success(request, f"Booking {booking_reference} cancelled. Simulated refund of INR {sum(b.total_amount for b in bookings):.2f} processed (ID: {refund_id}).")
    return redirect('profile')
