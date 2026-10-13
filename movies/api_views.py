from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from .models import Movie, Theater, Seat, Booking
from .serializers import MovieSerializer, TheaterSerializer, SeatSerializer, BookingSerializer

class MovieListAPIView(generics.ListAPIView):
    serializer_class = MovieSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = Movie.objects.all()
        search = self.request.GET.get('search')
        genre = self.request.GET.get('genre')
        language = self.request.GET.get('language')

        if search:
            queryset = queryset.filter(name__icontains=search)
        if genre:
            queryset = queryset.filter(genre__iexact=genre)
        if language:
            queryset = queryset.filter(language__iexact=language)
        return queryset

class MovieDetailAPIView(generics.RetrieveAPIView):
    queryset = Movie.objects.all()
    serializer_class = MovieSerializer
    permission_classes = [AllowAny]

class TheaterListAPIView(generics.ListAPIView):
    serializer_class = TheaterSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        movie_id = self.request.GET.get('movie_id')
        if movie_id:
            return Theater.objects.filter(movie_id=movie_id)
        return Theater.objects.all()

class TheaterDetailAPIView(generics.RetrieveAPIView):
    queryset = Theater.objects.all()
    serializer_class = TheaterSerializer
    permission_classes = [AllowAny]

class SeatListAPIView(generics.ListAPIView):
    serializer_class = SeatSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        theater_id = self.kwargs.get('theater_id')
        return Seat.objects.filter(theater_id=theater_id).order_by('seat_number')

class UserBookingsAPIView(generics.ListAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Booking.objects.filter(user=self.request.user).order_by('-booked_at')

class CalculatePriceAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        seat_ids = request.data.get('seat_ids', [])
        if not seat_ids:
            return Response({'error': 'No seat IDs provided'}, status=status.HTTP_400_BAD_REQUEST)

        seats = Seat.objects.filter(id__in=seat_ids)
        if not seats.exists():
            return Response({'error': 'Seats not found'}, status=status.HTTP_404_NOT_FOUND)

        ticket_total = sum(s.price for s in seats)
        convenience_fee = float(len(seats)) * 15.0
        gst = round(convenience_fee * 0.18, 2)
        grand_total = float(ticket_total) + convenience_fee + gst

        return Response({
            'seats_count': seats.count(),
            'seat_numbers': [s.seat_number for s in seats],
            'ticket_subtotal': float(ticket_total),
            'convenience_fee': convenience_fee,
            'gst': gst,
            'grand_total': round(grand_total, 2)
        })
