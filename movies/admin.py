from django.contrib import admin
from .models import Movie, Theater, Seat,Booking

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'genre', 'language', 'duration', 'release_date']
    search_fields = ['name', 'cast', 'genre', 'language', 'description']
    list_filter = ['genre', 'language']

@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'movie', 'location', 'time', 'price']
    search_fields = ['name', 'movie__name', 'location']
    list_filter = ['time', 'movie']
    actions = ['generate_sample_seats']

    @admin.action(description='Generate 30 sample seats (Rows A, B, C) for selected theaters')
    def generate_sample_seats(self, request, queryset):
        created_count = 0
        for theater in queryset:
            rows = [('A', 'VIP'), ('B', 'Premium'), ('C', 'Standard')]
            for row_letter, s_type in rows:
                for num in range(1, 11):
                    s_num = f'{row_letter}{num}'
                    _, created = Seat.objects.get_or_create(
                        theater=theater,
                        seat_number=s_num,
                        defaults={'seat_type': s_type, 'is_booked': False}
                    )
                    if created:
                        created_count += 1
        self.message_user(request, f'Successfully created {created_count} seats.')

@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['theater', 'seat_number', 'seat_type', 'is_booked']
    list_filter = ['theater', 'seat_type', 'is_booked']
    search_fields = ['seat_number', 'theater__name']
    actions = ['mark_available', 'mark_booked']

    @admin.action(description='Mark selected seats as available')
    def mark_available(self, request, queryset):
        queryset.update(is_booked=False)

    @admin.action(description='Mark selected seats as booked')
    def mark_booked(self, request, queryset):
        queryset.update(is_booked=True)

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['booking_reference', 'user', 'seat', 'movie', 'theater', 'total_amount', 'payment_status', 'booked_at']
    search_fields = ['booking_reference', 'user__username', 'movie__name', 'seat__seat_number']
    list_filter = ['payment_status', 'booked_at', 'theater']
