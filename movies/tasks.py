import logging
from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.utils import timezone
from .models import Booking, Seat
from .tickets import generate_ticket_pdf

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_ticket_email_async(self, booking_reference, recipient_email):
    """Generates PDF ticket and emails confirmation to customer asynchronously with automatic retry."""
    try:
        bookings = Booking.objects.filter(booking_reference=booking_reference)
        if not bookings.exists():
            logger.warning(f"Booking {booking_reference} not found for email dispatch.")
            return False

        first = bookings.first()
        movie_name = first.movie.name
        theater_name = first.theater.name
        show_time = first.theater.time.strftime('%Y-%m-%d %I:%M %p')
        seats_str = ', '.join([b.seat.seat_number for b in bookings])

        pdf_bytes = generate_ticket_pdf(booking_reference)

        subject = f"Your BookMySeat Confirmation: {movie_name} [{booking_reference}]"
        body_text = (
            f"Dear {first.user.username},\n\n"
            f"Thank you for booking with BookMySeat!\n"
            f"Your booking reference is {booking_reference}.\n\n"
            f"Movie: {movie_name}\n"
            f"Theatre: {theater_name}\n"
            f"Showtime: {show_time}\n"
            f"Seats: {seats_str}\n"
            f"Total Paid: INR {sum(b.total_amount for b in bookings):.2f}\n\n"
            f"Please find your official E-Ticket PDF attached. Have a great time!\n\n"
            f"Warm regards,\nBookMySeat Team"
        )

        email = EmailMultiAlternatives(
            subject=subject,
            body=body_text,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'tickets@bookmyseat.com'),
            to=[recipient_email]
        )
        email.attach(f"BookMySeat_Ticket_{booking_reference}.pdf", pdf_bytes, "application/pdf")
        email.send(fail_silently=False)

        bookings.update(email_sent=True)
        logger.info(f"Successfully dispatched ticket email for {booking_reference} to {recipient_email}")
        return True

    except Exception as exc:
        logger.error(f"Error sending ticket email for {booking_reference}: {exc}. Retrying...")
        raise self.retry(exc=exc)

@shared_task
def release_expired_seat_holds():
    """Background task to release expired 2-minute seat reservations."""
    now = timezone.now()
    expired_seats = Seat.objects.filter(
        is_booked=False,
        reserved_until__isnull=False,
        reserved_until__lte=now
    )
    count = expired_seats.count()
    if count > 0:
        expired_seats.update(reserved_until=None, reserved_by=None)
        logger.info(f"Released {count} expired seat holds.")
    return count
