from django.contrib import admin
from .models import Movie, Theater, Seat, Booking, Review, MoviePoster, MovieViewHistory

class MoviePosterInline(admin.TabularInline):
    model = MoviePoster
    extra = 1

class ReviewInline(admin.TabularInline):
    model = Review
    extra = 0
    readonly_fields = ['user', 'created_at']

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'genre', 'language', 'duration', 'release_date', 'age_rating']
    search_fields = ['name', 'cast', 'genre', 'language', 'description']
    list_filter = ['genre', 'language', 'age_rating']
    inlines = [MoviePosterInline, ReviewInline]

@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'movie', 'city', 'screen', 'time', 'price']
    search_fields = ['name', 'movie__name', 'city', 'location']
    list_filter = ['city', 'time', 'movie']
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
    list_display = ['theater', 'seat_number', 'seat_type', 'is_booked', 'reserved_until', 'reserved_by']
    list_filter = ['theater', 'seat_type', 'is_booked']
    search_fields = ['seat_number', 'theater__name']
    actions = ['mark_available', 'mark_booked', 'release_holds']

    @admin.action(description='Mark selected seats as available')
    def mark_available(self, request, queryset):
        queryset.update(is_booked=False, reserved_until=None, reserved_by=None)

    @admin.action(description='Mark selected seats as booked')
    def mark_booked(self, request, queryset):
        queryset.update(is_booked=True)

    @admin.action(description='Release active holds')
    def release_holds(self, request, queryset):
        queryset.update(reserved_until=None, reserved_by=None)

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['booking_reference', 'user', 'seat', 'movie', 'theater', 'total_amount', 'payment_status', 'is_refunded', 'booked_at']
    search_fields = ['booking_reference', 'user__username', 'movie__name', 'seat__seat_number', 'gateway_order_id', 'gateway_payment_id']
    list_filter = ['payment_status', 'is_refunded', 'booked_at', 'theater']
    readonly_fields = ['booked_at', 'booking_reference', 'gateway_order_id', 'gateway_payment_id', 'gateway_signature']

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['movie', 'user', 'rating', 'is_verified_viewer', 'is_reported', 'is_hidden', 'created_at']
    list_filter = ['is_reported', 'is_hidden', 'is_verified_viewer', 'rating']
    search_fields = ['movie__name', 'user__username', 'comment', 'report_reason']
    actions = ['hide_reviews', 'approve_reviews']

    @admin.action(description='Hide selected reviews from public display')
    def hide_reviews(self, request, queryset):
        queryset.update(is_hidden=True, is_reported=False)
        for r in queryset:
            r.movie.update_average_rating()

    @admin.action(description='Approve and restore selected reviews')
    def approve_reviews(self, request, queryset):
        queryset.update(is_hidden=False, is_reported=False, report_reason=None)
        for r in queryset:
            r.movie.update_average_rating()

@admin.register(MovieViewHistory)
class MovieViewHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'movie', 'viewed_at']
    list_filter = ['viewed_at']
    search_fields = ['user__username', 'movie__name']
