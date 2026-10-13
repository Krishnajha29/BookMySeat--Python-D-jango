import json
import hmac
import hashlib
import time
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.conf import settings

from movies.models import Movie, Theater, Seat, Booking, Review, MovieViewHistory
from movies.tickets import generate_ticket_pdf, generate_ticket_token, verify_ticket_token
from movies.tasks import send_ticket_email_async, release_expired_seat_holds
from movies.analytics import get_business_analytics, sanitize_csv_cell


class MasterBookMySeatTestSuite(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='krishna', password='password123', email='krishna@example.com')
        self.other_user = User.objects.create_user(username='other_viewer', password='password123', email='viewer@example.com')
        self.staff_user = User.objects.create_user(username='admin_staff', password='password123', email='admin@example.com', is_staff=True)

        # Movies
        self.movie1 = Movie.objects.create(
            name='Avengers: Endgame',
            rating=Decimal('8.9'),
            cast='Robert Downey Jr, Chris Evans',
            description='The epic conclusion to the Infinity Saga.',
            genre='Action',
            language='English',
            duration=181,
            release_date=timezone.now().date() - timedelta(days=50),
            trailer_url='https://www.youtube.com/watch?v=TcMBFSGVi1c',
            age_rating='UA'
        )

        self.movie2 = Movie.objects.create(
            name='Dangal',
            rating=Decimal('8.4'),
            cast='Aamir Khan, Fatima Sana Shaikh',
            description='Biographical sports drama of wrestling champions.',
            genre='Drama',
            language='Hindi',
            duration=161,
            release_date=timezone.now().date() - timedelta(days=10),
            trailer_url='https://youtu.be/x_7YlGv9u1g',
            age_rating='U'
        )

        self.movie3 = Movie.objects.create(
            name='Interstellar',
            rating=Decimal('8.7'),
            cast='Matthew McConaughey, Anne Hathaway',
            description='Exploration of space through a wormhole.',
            genre='Sci-Fi',
            language='English',
            duration=169,
            release_date=timezone.now().date() - timedelta(days=200),
            trailer_url='https://www.youtube.com/embed/zSWdZVtXT7E',
            age_rating='UA'
        )

        # Theatres
        self.theater1 = Theater.objects.create(
            name='PVR Forum Mall',
            movie=self.movie1,
            time=timezone.now() + timedelta(days=1),
            location='Audi 1',
            city='Bengaluru',
            screen='Screen 1',
            price=Decimal('200.00')
        )

        self.theater2 = Theater.objects.create(
            name='INOX Lido Mall',
            movie=self.movie2,
            time=timezone.now() + timedelta(days=2),
            location='Audi 2',
            city='Mumbai',
            screen='Screen 2',
            price=Decimal('150.00')
        )

        # Seats
        self.seat_a1 = Seat.objects.create(theater=self.theater1, seat_number='A1', seat_type='VIP', is_booked=False)
        self.seat_a2 = Seat.objects.create(theater=self.theater1, seat_number='A2', seat_type='VIP', is_booked=False)
        self.seat_b1 = Seat.objects.create(theater=self.theater1, seat_number='B1', seat_type='Standard', is_booked=False)

    # ==========================================================================
    # REQUIREMENT 1: DISCOVERY, SEARCH, FILTERS, SORTING, PAGINATION & RECOMMENDATIONS
    # ==========================================================================

    def test_movie_search_by_title_and_cast(self):
        # Search by title
        res = self.client.get(reverse('movie_list'), {'search': 'Endgame'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Avengers: Endgame')
        self.assertNotContains(res, 'Dangal')

        # Search by cast
        res_cast = self.client.get(reverse('movie_list'), {'search': 'Aamir Khan'})
        self.assertEqual(res_cast.status_code, 200)
        self.assertContains(res_cast, 'Dangal')
        self.assertNotContains(res_cast, 'Avengers: Endgame')

    def test_movie_filtering_by_genre_language_city_and_rating(self):
        # Filter by genre
        res_genre = self.client.get(reverse('movie_list'), {'genre': 'Action'})
        self.assertContains(res_genre, 'Avengers: Endgame')
        self.assertNotContains(res_genre, 'Dangal')

        # Filter by language
        res_lang = self.client.get(reverse('movie_list'), {'language': 'Hindi'})
        self.assertContains(res_lang, 'Dangal')
        self.assertNotContains(res_lang, 'Avengers: Endgame')

        # Filter by city
        res_city = self.client.get(reverse('movie_list'), {'city': 'Bengaluru'})
        self.assertContains(res_city, 'Avengers: Endgame')
        self.assertNotContains(res_city, 'Dangal')

    def test_movie_sorting_and_dynamic_count(self):
        # Sorting by rating descending
        res = self.client.get(reverse('movie_list'), {'sort': 'rating'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['result_count'], 3)
        movies = list(res.context['movies'])
        self.assertEqual(movies[0].name, 'Avengers: Endgame')  # 8.9 rating

    def test_personalized_recommendations_based_on_user_history(self):
        # Logged in user with booking history in Action genre
        self.client.login(username='krishna', password='password123')
        Booking.objects.create(
            user=self.user,
            seat=self.seat_a1,
            movie=self.movie1,  # Action
            theater=self.theater1,
            booking_reference='BMS-REC-01',
            total_amount=Decimal('200.00'),
            payment_status='Completed'
        )

        # View movie list
        res = self.client.get(reverse('movie_list'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('recommended_movies', res.context)
        self.assertGreaterEqual(len(res.context['recommended_movies']), 1)

    # ==========================================================================
    # REQUIREMENT 2: AUTOMATED PDF TICKETS & EMAIL CONFIRMATION
    # ==========================================================================

    def test_pdf_ticket_generation_and_qr_verification(self):
        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat_b1,
            movie=self.movie1,
            theater=self.theater1,
            booking_reference='BMS-PDF-TEST',
            total_amount=Decimal('200.00'),
            payment_status='Completed'
        )

        # 1. Generate PDF
        pdf_bytes = generate_ticket_pdf('BMS-PDF-TEST')
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))

        # 2. QR Token verification
        token = generate_ticket_token('BMS-PDF-TEST')
        verify_result = verify_ticket_token(token)
        self.assertTrue(verify_result['valid'])
        self.assertEqual(verify_result['booking_reference'], 'BMS-PDF-TEST')
        self.assertEqual(verify_result['movie'], 'Avengers: Endgame')

        # 3. Download ticket view authorization check
        self.client.login(username='krishna', password='password123')
        download_res = self.client.get(reverse('download_ticket_pdf', args=['BMS-PDF-TEST']))
        self.assertEqual(download_res.status_code, 200)
        self.assertEqual(download_res['Content-Type'], 'application/pdf')

        # Other user cannot download
        self.client.login(username='other_viewer', password='password123')
        unauth_res = self.client.get(reverse('download_ticket_pdf', args=['BMS-PDF-TEST']))
        self.assertEqual(unauth_res.status_code, 403)

    def test_celery_async_email_task_execution(self):
        Booking.objects.create(
            user=self.user,
            seat=self.seat_a2,
            movie=self.movie1,
            theater=self.theater1,
            booking_reference='BMS-TASK-EMAIL',
            total_amount=Decimal('200.00'),
            payment_status='Completed'
        )
        # Execute Celery task
        result = send_ticket_email_async('BMS-TASK-EMAIL', 'test@example.com')
        self.assertTrue(result)
        booking = Booking.objects.get(booking_reference='BMS-TASK-EMAIL')
        self.assertTrue(booking.email_sent)

    # ==========================================================================
    # REQUIREMENT 3: MOVIE MANAGEMENT, TRAILERS, REVIEWS & RATINGS
    # ==========================================================================

    def test_youtube_trailer_url_normalization(self):
        # Watch URL format
        self.assertEqual(
            self.movie1.get_youtube_embed_url(),
            'https://www.youtube.com/embed/TcMBFSGVi1c?rel=0&modestbranding=1'
        )
        # Short youtu.be format
        self.assertEqual(
            self.movie2.get_youtube_embed_url(),
            'https://www.youtube.com/embed/x_7YlGv9u1g?rel=0&modestbranding=1'
        )

    def test_verified_viewer_review_submission_and_eligibility(self):
        # User without booking cannot review
        self.client.login(username='krishna', password='password123')
        res_fail = self.client.post(reverse('submit_or_edit_review', args=[self.movie2.id]), {
            'rating': 9,
            'comment': 'Amazing movie!'
        })
        self.assertEqual(Review.objects.filter(movie=self.movie2, user=self.user).count(), 0)

        # Create verified booking for movie2
        seat_inox = Seat.objects.create(theater=self.theater2, seat_number='C1', is_booked=True)
        Booking.objects.create(
            user=self.user,
            seat=seat_inox,
            movie=self.movie2,
            theater=self.theater2,
            booking_reference='BMS-REVIEW-OK',
            payment_status='Completed'
        )

        # Now submit review
        res_ok = self.client.post(reverse('submit_or_edit_review', args=[self.movie2.id]), {
            'rating': 10,
            'comment': 'Outstanding performances and screenplay!'
        })
        self.assertEqual(res_ok.status_code, 302)
        review = Review.objects.get(movie=self.movie2, user=self.user)
        self.assertTrue(review.is_verified_viewer)
        self.assertEqual(review.rating, 10)

    def test_review_reporting_and_admin_moderation(self):
        review = Review.objects.create(
            movie=self.movie1,
            user=self.other_user,
            rating=2,
            comment='Bad quality spoiler content',
            is_verified_viewer=True
        )

        # Report review
        self.client.login(username='krishna', password='password123')
        self.client.post(reverse('report_review', args=[review.id]), {'reason': 'Contains spoilers'})
        review.refresh_from_db()
        self.assertTrue(review.is_reported)

        # Admin moderation: hide review
        self.client.login(username='admin_staff', password='password123')
        self.client.post(reverse('moderate_review', args=[review.id]), {'action': 'hide'})
        review.refresh_from_db()
        self.assertTrue(review.is_hidden)
        self.assertFalse(review.is_reported)

    # ==========================================================================
    # REQUIREMENT 4: PAYMENT INTEGRATION & WEBHOOK VERIFICATION
    # ==========================================================================

    def test_payment_webhook_hmac_signature_verification(self):
        secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', 'test_webhook_secret_demo').encode('utf-8')
        order_id = 'order_webhook_test_123'

        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat_a1,
            movie=self.movie1,
            theater=self.theater1,
            booking_reference='BMS-WH-01',
            gateway_order_id=order_id,
            payment_status='Pending'
        )

        payload = json.dumps({
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test_999",
                        "order_id": order_id
                    }
                }
            }
        }).encode('utf-8')

        valid_sig = hmac.new(secret, payload, hashlib.sha256).hexdigest()

        # 1. Valid Signature Test
        response = self.client.post(
            reverse('payment_webhook'),
            data=payload,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=valid_sig
        )
        self.assertEqual(response.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, 'Completed')
        self.assertEqual(booking.gateway_payment_id, 'pay_test_999')

        # 2. Invalid Signature Test
        bad_response = self.client.post(
            reverse('payment_webhook'),
            data=payload,
            content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE='forged_invalid_signature'
        )
        self.assertEqual(bad_response.status_code, 403)

    def test_booking_cancellation_and_refund_recording(self):
        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat_b1,
            movie=self.movie1,
            theater=self.theater1,
            booking_reference='BMS-REFUND-01',
            total_amount=Decimal('200.00'),
            payment_status='Completed'
        )
        self.seat_b1.is_booked = True
        self.seat_b1.save()

        self.client.login(username='krishna', password='password123')
        cancel_res = self.client.post(reverse('cancel_booking', args=['BMS-REFUND-01']))
        self.assertEqual(cancel_res.status_code, 302)

        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, 'Cancelled')
        self.assertTrue(booking.is_refunded)
        self.assertEqual(booking.refund_amount, Decimal('200.00'))

        self.seat_b1.refresh_from_db()
        self.assertFalse(self.seat_b1.is_booked)

    # ==========================================================================
    # REQUIREMENT 5: LIVE SEAT AVAILABILITY & TWO-MINUTE RESERVATIONS
    # ==========================================================================

    def test_two_minute_reservation_hold_and_expiry(self):
        self.client.login(username='krishna', password='password123')

        # 1. Create 2-minute hold
        res = self.client.post(reverse('book_seats', args=[self.theater1.id]), {'seats': [self.seat_a1.id]})
        self.assertEqual(res.status_code, 302)

        self.seat_a1.refresh_from_db()
        self.assertTrue(self.seat_a1.is_hold_active())
        self.assertEqual(self.seat_a1.reserved_by, self.user)
        self.assertEqual(self.seat_a1.get_status_for_user(self.user), 'selected_by_me')
        self.assertEqual(self.seat_a1.get_status_for_user(self.other_user), 'reserved')

        # 2. Second user cannot take the held seat
        self.client.login(username='other_viewer', password='password123')
        res_conflict = self.client.post(reverse('book_seats', args=[self.theater1.id]), {'seats': [self.seat_a1.id]})
        self.assertEqual(res_conflict.status_code, 200)
        self.assertContains(res_conflict, 'Reserved by another user')

        # 3. Simulate hold expiration
        self.seat_a1.reserved_until = timezone.now() - timedelta(seconds=10)
        self.seat_a1.save()

        # Task cleans up expired holds
        released_count = release_expired_seat_holds()
        self.assertGreaterEqual(released_count, 1)

        self.seat_a1.refresh_from_db()
        self.assertFalse(self.seat_a1.is_hold_active())
        self.assertEqual(self.seat_a1.get_status_for_user(self.other_user), 'available')

    # ==========================================================================
    # REQUIREMENT 6: ADMIN DASHBOARD & BUSINESS ANALYTICS
    # ==========================================================================

    def test_admin_dashboard_access_control(self):
        # Non-staff user gets redirected or forbidden
        self.client.login(username='krishna', password='password123')
        res_denied = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(res_denied.status_code, 302)

        # Staff user gets access
        self.client.login(username='admin_staff', password='password123')
        res_allowed = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(res_allowed.status_code, 200)
        self.assertContains(res_allowed, 'Business Analytics & Admin Dashboard')

    def test_csv_export_formula_injection_protection(self):
        self.client.login(username='admin_staff', password='password123')

        # Formula injection characters test
        self.assertEqual(sanitize_csv_cell("=1+1"), "'=1+1")
        self.assertEqual(sanitize_csv_cell("+cmd|"), "'+cmd|")
        self.assertEqual(sanitize_csv_cell("@SUM(A1)"), "'@SUM(A1)")
        self.assertEqual(sanitize_csv_cell("Safe Title"), "Safe Title")

        # Export CSV test
        csv_res = self.client.get(reverse('export_analytics_csv'))
        self.assertEqual(csv_res.status_code, 200)
        self.assertEqual(csv_res['Content-Type'], 'text/csv')
        self.assertIn('BookMySeat Business Analytics Report', csv_res.content.decode('utf-8'))

    def test_analytics_kpis_calculation(self):
        Booking.objects.create(
            user=self.user,
            seat=self.seat_a1,
            movie=self.movie1,
            theater=self.theater1,
            booking_reference='BMS-KPI-01',
            total_amount=Decimal('350.00'),
            payment_status='Completed'
        )

        analytics = get_business_analytics()
        self.assertGreaterEqual(analytics['gross_revenue'], Decimal('350.00'))
        self.assertGreaterEqual(analytics['total_bookings_count'], 1)
        self.assertIn('rev_by_day', analytics)
        self.assertIn('theatre_occupancies', analytics)
