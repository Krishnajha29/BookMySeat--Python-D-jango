from django.db import models
from django.contrib.auth.models import User 


class Movie(models.Model):
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="movies/")
    rating = models.DecimalField(max_digits=3, decimal_places=1)
    cast = models.TextField()
    description = models.TextField(blank=True, null=True) # optional
    genre = models.CharField(max_length=100, default='Action', blank=True)
    language = models.CharField(max_length=50, default='English', blank=True)
    duration = models.PositiveIntegerField(default=120, help_text='Duration in minutes')
    release_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.name

class Theater(models.Model):
    name = models.CharField(max_length=255)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='theaters')
    time = models.DateTimeField()
    location = models.CharField(max_length=255, default='Audi 1', blank=True)
    price = models.DecimalField(max_digits=6, decimal_places=2, default=150.00)

    def __str__(self):
        return f'{self.name} - {self.movie.name} at {self.time}'

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

    @property
    def price(self):
        base_price = self.theater.price
        if self.seat_type == 'VIP':
            return base_price + 100
        elif self.seat_type == 'Premium':
            return base_price + 50
        return base_price

    def __str__(self):
        return f'{self.seat_number} ({self.seat_type}) in {self.theater.name}'

class Booking(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Completed', 'Completed'),
        ('Failed', 'Failed'),
        ('Cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    seat = models.OneToOneField(Seat, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    theater = models.ForeignKey(Theater, on_delete=models.CASCADE)
    booked_at = models.DateTimeField(auto_now_add=True)
    booking_reference = models.CharField(max_length=32, blank=True, null=True, db_index=True)
    total_amount = models.DecimalField(max_digits=8, decimal_places=2, default=150.00)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='Completed')
    payment_method = models.CharField(max_length=50, default='Simulated Card', blank=True)

    def __str__(self):
        ref = self.booking_reference or f'ID-{self.id}'
        return f'Booking {ref} by {self.user.username} for {self.seat.seat_number} at {self.theater.name}'