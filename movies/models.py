import re
from urllib.parse import parse_qs, urlparse
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Movie(models.Model):
    AGE_RATINGS = [
        ('U', 'U - Universal'),
        ('UA', 'UA - Parental Guidance'),
        ('A', 'A - Adults Only'),
        ('S', 'S - Specialized Audience'),
    ]

    name = models.CharField(max_length=255, db_index=True)
    image = models.ImageField(upload_to="movies/")
    rating = models.DecimalField(max_digits=3, decimal_places=1, default=8.0)
    cast = models.TextField()
    description = models.TextField(blank=True, null=True)
    genre = models.CharField(max_length=100, default='Action', blank=True, db_index=True)
    language = models.CharField(max_length=50, default='English', blank=True, db_index=True)
    duration = models.PositiveIntegerField(default=120, help_text='Duration in minutes')
    release_date = models.DateField(null=True, blank=True, db_index=True)
    trailer_url = models.URLField(max_length=500, blank=True, null=True)
    age_rating = models.CharField(max_length=10, choices=AGE_RATINGS, default='UA')

    def __str__(self):
        return self.name

    def get_youtube_embed_url(self):
        """Validates and normalizes YouTube URLs into secure embed links."""
        if not self.trailer_url:
            return None
        parsed = urlparse(self.trailer_url)
        video_id = None
        if parsed.hostname in ('www.youtube.com', 'youtube.com'):
            if parsed.path == '/watch':
                video_id = parse_qs(parsed.query).get('v', [None])[0]
            elif parsed.path.startswith('/embed/'):
                video_id = parsed.path.split('/')[2]
        elif parsed.hostname == 'youtu.be':
            video_id = parsed.path.lstrip('/')

        if video_id and re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
            return f"https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1"
        return None

    def update_average_rating(self):
        """Recalculates average rating from active reviews."""
        avg = self.reviews.filter(is_hidden=False).aggregate(models.Avg('rating'))['rating__avg']
        if avg:
            self.rating = round(avg, 1)
            self.save(update_fields=['rating'])


class MoviePoster(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='posters')
    image = models.ImageField(upload_to="movies/posters/")
    caption = models.CharField(max_length=200, blank=True)
    is_primary = models.BooleanField(default=False)

    def __str__(self):
        return f"Poster for {self.movie.name} ({self.caption or 'Untitled'})"


class Theater(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='theaters')
    time = models.DateTimeField(db_index=True)
    location = models.CharField(max_length=255, default='Audi 1', blank=True)
    city = models.CharField(max_length=100, default='Bengaluru', db_index=True)
    screen = models.CharField(max_length=50, default='Screen 1', blank=True)
    price = models.DecimalField(max_digits=6, decimal_places=2, default=150.00)

    class Meta:
        indexes = [
            models.Index(fields=['city', 'time']),
            models.Index(fields=['movie', 'city']),
        ]

    def __str__(self):
        return f'{self.name} ({self.city}) - {self.movie.name} at {self.time}'


class Seat(models.Model):
    SEAT_TYPES = [
        ('Standard', 'Standard'),
        ('Premium', 'Premium'),
        ('VIP', 'VIP'),
    ]

    theater = models.ForeignKey(Theater, on_delete=models.CASCADE, related_name='seats')
    seat_number = models.CharField(max_length=10)
    is_booked = models.BooleanField(default=False)
    seat_type = models.CharField(max_length=20, choices=SEAT_TYPES, default='Standard')
    reserved_until = models.DateTimeField(null=True, blank=True, db_index=True)
    reserved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='held_seats')

    class Meta:
        unique_together = ('theater', 'seat_number')
        indexes = [
            models.Index(fields=['theater', 'is_booked']),
            models.Index(fields=['reserved_until']),
        ]

    @property
    def price(self):
        base_price = self.theater.price
        if self.seat_type == 'VIP':
            return base_price + 100
        elif self.seat_type == 'Premium':
            return base_price + 50
        return base_price

    def is_hold_active(self):
        if self.reserved_until and self.reserved_until > timezone.now():
            return True
        return False

    def get_status_for_user(self, user=None):
        if self.is_booked:
            return 'booked'
        if self.is_hold_active():
            if user and user.is_authenticated and self.reserved_by_id == user.id:
                return 'selected_by_me'
            return 'reserved'
        return 'available'

    def __str__(self):
        return f'{self.seat_number} ({self.seat_type}) in {self.theater.name}'


class Booking(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Completed', 'Completed'),
        ('Failed', 'Failed'),
        ('Cancelled', 'Cancelled'),
        ('Refunded', 'Refunded'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, db_index=True)
    seat = models.OneToOneField(Seat, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, db_index=True)
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE, db_index=True)
    booked_at = models.DateTimeField(auto_now_add=True, db_index=True)
    booking_reference = models.CharField(max_length=32, blank=True, null=True, db_index=True)
    total_amount = models.DecimalField(max_digits=8, decimal_places=2, default=150.00)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='Completed', db_index=True)
    payment_method = models.CharField(max_length=50, default='Simulated Card', blank=True)
    gateway_order_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    gateway_payment_id = models.CharField(max_length=100, blank=True, null=True)
    gateway_signature = models.CharField(max_length=255, blank=True, null=True)
    refund_id = models.CharField(max_length=100, blank=True, null=True)
    refund_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    is_refunded = models.BooleanField(default=False)
    email_sent = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['booked_at', 'payment_status']),
            models.Index(fields=['user', 'booked_at']),
        ]

    def __str__(self):
        ref = self.booking_reference or f'ID-{self.id}'
        return f'Booking {ref} by {self.user.username} for {self.seat.seat_number} at {self.theater.name}'


class Review(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField(choices=[(i, f'{i} Stars') for i in range(1, 11)], default=10)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_reported = models.BooleanField(default=False)
    report_reason = models.TextField(blank=True, null=True)
    is_hidden = models.BooleanField(default=False)
    is_verified_viewer = models.BooleanField(default=False)

    class Meta:
        unique_together = ('movie', 'user')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} review on {self.movie.name} ({self.rating}/10)"


class MovieViewHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='view_history')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='views')
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'movie')
        ordering = ['-viewed_at']

    def __str__(self):
        return f"{self.user.username} viewed {self.movie.name} at {self.viewed_at}"