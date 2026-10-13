from rest_framework import serializers
from .models import Movie, Theater, Seat, Booking
from django.contrib.auth.models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class MovieSerializer(serializers.ModelSerializer):
    class Meta:
        model = Movie
        fields = ['id', 'name', 'image', 'rating', 'cast', 'description', 'genre', 'language', 'duration', 'release_date']

class SeatSerializer(serializers.ModelSerializer):
    price = serializers.ReadOnlyField()

    class Meta:
        model = Seat
        fields = ['id', 'seat_number', 'seat_type', 'is_booked', 'price', 'theater']

class TheaterSerializer(serializers.ModelSerializer):
    movie_name = serializers.ReadOnlyField(source='movie.name')
    seats_count = serializers.SerializerMethodField()
    available_seats_count = serializers.SerializerMethodField()

    class Meta:
        model = Theater
        fields = ['id', 'name', 'movie', 'movie_name', 'time', 'location', 'price', 'seats_count', 'available_seats_count']

    def get_seats_count(self, obj):
        return obj.seats.count()

    def get_available_seats_count(self, obj):
        return obj.seats.filter(is_booked=False).count()

class BookingSerializer(serializers.ModelSerializer):
    movie_name = serializers.ReadOnlyField(source='movie.name')
    theater_name = serializers.ReadOnlyField(source='theater.name')
    seat_number = serializers.ReadOnlyField(source='seat.seat_number')
    username = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_reference', 'user', 'username', 'movie', 'movie_name',
            'theater', 'theater_name', 'seat', 'seat_number', 'total_amount',
            'payment_status', 'payment_method', 'booked_at'
        ]
        read_only_fields = ['id', 'booked_at', 'booking_reference', 'user']
