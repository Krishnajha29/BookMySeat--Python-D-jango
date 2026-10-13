from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
from movies.models import Movie, Theater, Seat, Booking

class MovieBookingTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password123', email='test@example.com')
        self.other_user = User.objects.create_user(username='otheruser', password='password123', email='other@example.com')

        self.movie = Movie.objects.create(
            name='Inception',
            rating=Decimal('8.8'),
            cast='Leonardo DiCaprio, Joseph Gordon-Levitt',
            description='A thief who enters dreams of others.',
            genre='Sci-Fi',
            language='English',
            duration=148
        )

        self.movie2 = Movie.objects.create(
            name='Dangal',
            rating=Decimal('8.4'),
            cast='Aamir Khan',
            description='Biographical sports drama.',
            genre='Drama',
            language='Hindi',
            duration=161
        )

        self.theater = Theater.objects.create(
            name='PVR Cinemas Forum',
            movie=self.movie,
            time=timezone.now() + timezone.timedelta(days=1),
            location='Screen 2, Audi A',
            price=Decimal('200.00')
        )

        self.seat_vip = Seat.objects.create(
            theater=self.theater,
            seat_number='A1',
            seat_type='VIP',
            is_booked=False
        )

        self.seat_std = Seat.objects.create(
            theater=self.theater,
            seat_number='B1',
            seat_type='Standard',
            is_booked=False
        )

    def test_movie_list_and_search(self):
        # Search by name
        response = self.client.get(reverse('movie_list'), {'search': 'Inception'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Inception')
        self.assertNotContains(response, 'Dangal')

    def test_movie_filter_by_genre_and_language(self):
        # Filter by genre
        response = self.client.get(reverse('movie_list'), {'genre': 'Drama'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dangal')
        self.assertNotContains(response, 'Inception')

        # Filter by language
        response_lang = self.client.get(reverse('movie_list'), {'language': 'English'})
        self.assertContains(response_lang, 'Inception')
        self.assertNotContains(response_lang, 'Dangal')

    def test_movie_detail_view(self):
        response = self.client.get(reverse('movie_detail', args=[self.movie.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Inception')
        self.assertContains(response, 'PVR Cinemas Forum')

    def test_theater_list_view(self):
        response = self.client.get(reverse('theater_list', args=[self.movie.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PVR Cinemas Forum')

    def test_seat_selection_requires_login(self):
        response = self.client.get(reverse('book_seats', args=[self.theater.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_seat_selection_and_summary_flow(self):
        self.client.login(username='testuser', password='password123')

        # GET seat selection page
        response = self.client.get(reverse('book_seats', args=[self.theater.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A1')

        # POST valid seat selection
        post_response = self.client.post(reverse('book_seats', args=[self.theater.id]), {
            'seats': [self.seat_vip.id, self.seat_std.id]
        })
        self.assertEqual(post_response.status_code, 302)
        self.assertRedirects(post_response, reverse('booking_summary', args=[self.theater.id]))

        # GET booking summary
        summary_response = self.client.get(reverse('booking_summary', args=[self.theater.id]))
        self.assertEqual(summary_response.status_code, 200)
        self.assertContains(summary_response, 'Review Your Ticket Details')
        self.assertContains(summary_response, 'A1')
        self.assertContains(summary_response, 'B1')

    def test_prevent_booking_already_booked_seat(self):
        self.client.login(username='testuser', password='password123')
        self.seat_vip.is_booked = True
        self.seat_vip.save()

        response = self.client.post(reverse('book_seats', args=[self.theater.id]), {
            'seats': [self.seat_vip.id]
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already booked')

    def test_payment_simulation_success(self):
        self.client.login(username='testuser', password='password123')

        # Select seat
        self.client.post(reverse('book_seats', args=[self.theater.id]), {'seats': [self.seat_std.id]})
        self.client.get(reverse('booking_summary', args=[self.theater.id]))

        # Simulate Payment Success
        pay_response = self.client.post(reverse('payment_process', args=[self.theater.id]), {
            'action': 'pay',
            'payment_method': 'Simulated UPI'
        })
        self.assertEqual(pay_response.status_code, 302)

        # Verify seat is marked booked
        self.seat_std.refresh_from_db()
        self.assertTrue(self.seat_std.is_booked)

        # Verify booking record created
        booking = Booking.objects.filter(user=self.user, seat=self.seat_std).first()
        self.assertIsNotNone(booking)
        self.assertEqual(booking.payment_status, 'Completed')
        self.assertTrue(booking.booking_reference.startswith('BMS-'))

        # Verify confirmation page viewable by owner
        confirm_url = reverse('booking_confirmation', args=[booking.booking_reference])
        confirm_response = self.client.get(confirm_url)
        self.assertEqual(confirm_response.status_code, 200)
        self.assertContains(confirm_response, booking.booking_reference)

    def test_payment_simulation_failure_does_not_book_seats(self):
        self.client.login(username='testuser', password='password123')

        # Select seat
        self.client.post(reverse('book_seats', args=[self.theater.id]), {'seats': [self.seat_std.id]})
        self.client.get(reverse('booking_summary', args=[self.theater.id]))

        # Simulate Payment Failure
        fail_response = self.client.post(reverse('payment_process', args=[self.theater.id]), {
            'action': 'fail',
            'payment_method': 'Demo Card'
        })
        self.assertEqual(fail_response.status_code, 200)
        self.assertContains(fail_response, 'declined or cancelled')

        # Verify seat remains unbooked
        self.seat_std.refresh_from_db()
        self.assertFalse(self.seat_std.is_booked)
        self.assertEqual(Booking.objects.filter(seat=self.seat_std).count(), 0)

    def test_user_cannot_access_other_users_booking_confirmation(self):
        # Create booking for testuser
        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat_vip,
            movie=self.movie,
            theater=self.theater,
            booking_reference='BMS-SECRET12',
            total_amount=Decimal('300.00'),
            payment_status='Completed'
        )
        self.seat_vip.is_booked = True
        self.seat_vip.save()

        # Login as other_user and try to view testuser's confirmation
        self.client.login(username='otheruser', password='password123')
        response = self.client.get(reverse('booking_confirmation', args=['BMS-SECRET12']))
        self.assertEqual(response.status_code, 403)

    def test_cancel_booking_releases_seat(self):
        self.client.login(username='testuser', password='password123')

        booking = Booking.objects.create(
            user=self.user,
            seat=self.seat_std,
            movie=self.movie,
            theater=self.theater,
            booking_reference='BMS-CANCEL01',
            total_amount=Decimal('200.00'),
            payment_status='Completed'
        )
        self.seat_std.is_booked = True
        self.seat_std.save()

        # Cancel the booking
        cancel_response = self.client.post(reverse('cancel_booking', args=['BMS-CANCEL01']))
        self.assertEqual(cancel_response.status_code, 302)

        # Verify booking status cancelled & seat freed
        booking.refresh_from_db()
        self.assertEqual(booking.payment_status, 'Cancelled')
        self.seat_std.refresh_from_db()
        self.assertFalse(self.seat_std.is_booked)

    def test_drf_api_endpoints(self):
        # Movie List API
        response = self.client.get(reverse('api_movie_list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)

        # Movie Detail API
        detail_response = self.client.get(reverse('api_movie_detail', args=[self.movie.id]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.data['name'], 'Inception')

        # Seat List API
        seats_response = self.client.get(reverse('api_seat_list', args=[self.theater.id]))
        self.assertEqual(seats_response.status_code, 200)
        self.assertGreaterEqual(len(seats_response.data), 2)

        # Price Calculator API
        calc_response = self.client.post(
            reverse('api_calculate_price'),
            {'seat_ids': [self.seat_vip.id, self.seat_std.id]},
            content_type='application/json'
        )
        self.assertEqual(calc_response.status_code, 200)
        self.assertIn('grand_total', calc_response.data)
        self.assertEqual(calc_response.data['seats_count'], 2)
