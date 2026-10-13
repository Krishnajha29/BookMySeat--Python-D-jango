import csv
import io
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum, Count, Avg, F, Q, Case, When, Value, FloatField
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear, ExtractHour
from django.contrib.auth.models import User
from .models import Movie, Theater, Seat, Booking

def sanitize_csv_cell(value):
    """Prevents CSV formula injection by quoting or escaping dangerous starting characters."""
    if value is None:
        return ""
    str_val = str(value)
    if str_val.startswith(('=', '+', '-', '@', '\t', '\r')):
        return f"'{str_val}"
    return str_val

def get_business_analytics(start_date=None, end_date=None):
    """Calculates all 12 key business analytics using optimized SQL aggregation."""
    now = timezone.now()
    if not end_date:
        end_date = now
    if not start_date:
        start_date = end_date - timedelta(days=30)

    # Base query for the filtered period
    bookings_qs = Booking.objects.filter(booked_at__gte=start_date, booked_at__lte=end_date)
    completed_bookings = bookings_qs.filter(payment_status='Completed')

    # 1. Total revenue by day, week, month, year
    rev_by_day = list(
        completed_bookings.annotate(period=TruncDay('booked_at'))
        .values('period')
        .annotate(total=Sum('total_amount'), count=Count('id'))
        .order_by('-period')[:15]
    )

    rev_by_week = list(
        completed_bookings.annotate(period=TruncWeek('booked_at'))
        .values('period')
        .annotate(total=Sum('total_amount'), count=Count('id'))
        .order_by('-period')[:12]
    )

    rev_by_month = list(
        completed_bookings.annotate(period=TruncMonth('booked_at'))
        .values('period')
        .annotate(total=Sum('total_amount'), count=Count('id'))
        .order_by('-period')[:12]
    )

    rev_by_year = list(
        completed_bookings.annotate(period=TruncYear('booked_at'))
        .values('period')
        .annotate(total=Sum('total_amount'), count=Count('id'))
        .order_by('-period')
    )

    # 2. Overall Revenue Aggregates
    gross_revenue = completed_bookings.aggregate(s=Sum('total_amount'))['s'] or Decimal('0.00')
    refund_stats = bookings_qs.filter(Q(payment_status='Refunded') | Q(is_refunded=True)).aggregate(
        total_refunded=Sum('refund_amount'),
        refund_count=Count('id')
    )
    total_refunded = refund_stats['total_refunded'] or Decimal('0.00')
    net_revenue = gross_revenue - total_refunded

    # 3. Cancellation & Refund statistics
    cancellation_count = bookings_qs.filter(payment_status='Cancelled').count()
    total_bookings_count = bookings_qs.count()
    cancellation_rate = round((cancellation_count / total_bookings_count * 100), 2) if total_bookings_count else 0.0

    # 4. Most-booked movies
    most_booked_movies = list(
        Movie.objects.filter(booking__in=completed_bookings)
        .annotate(
            tickets_sold=Count('booking'),
            revenue=Sum('booking__total_amount')
        )
        .order_by('-tickets_sold')[:5]
    )

    # 5. Top-performing theatres
    top_theaters = list(
        Theater.objects.filter(booking__in=completed_bookings)
        .annotate(
            tickets_sold=Count('booking'),
            revenue=Sum('booking__total_amount')
        )
        .order_by('-revenue')[:5]
    )

    # 6. Theatre Occupancy Percentages
    # Capacity = total seats across theaters in period, occupancy = booked seats
    theaters_in_period = Theater.objects.filter(time__gte=start_date, time__lte=end_date)
    theatre_occupancies = []
    for th in theaters_in_period[:8]:
        capacity = th.seats.count()
        booked = th.seats.filter(is_booked=True).count()
        occupancy_pct = round((booked / capacity * 100), 1) if capacity else 0.0
        theatre_occupancies.append({
            'theater': th.name,
            'city': th.city,
            'capacity': capacity,
            'booked': booked,
            'occupancy_pct': occupancy_pct
        })

    # 7. Peak booking hours
    peak_hours = list(
        completed_bookings.annotate(hour=ExtractHour('booked_at'))
        .values('hour')
        .annotate(count=Count('id'), volume=Sum('total_amount'))
        .order_by('-count')[:5]
    )

    # 8. User growth reports
    user_growth = list(
        User.objects.filter(date_joined__gte=start_date, date_joined__lte=end_date)
        .annotate(day=TruncDay('date_joined'))
        .values('day')
        .annotate(new_users=Count('id'))
        .order_by('-day')[:10]
    )
    total_users_count = User.objects.count()

    return {
        'start_date': start_date,
        'end_date': end_date,
        'total_bookings_count': total_bookings_count,
        'gross_revenue': gross_revenue,
        'total_refunded': total_refunded,
        'net_revenue': net_revenue,
        'cancellation_count': cancellation_count,
        'cancellation_rate': cancellation_rate,
        'refund_count': refund_stats['refund_count'] or 0,
        'rev_by_day': rev_by_day,
        'rev_by_week': rev_by_week,
        'rev_by_month': rev_by_month,
        'rev_by_year': rev_by_year,
        'most_booked_movies': most_booked_movies,
        'top_theaters': top_theaters,
        'theatre_occupancies': theatre_occupancies,
        'peak_hours': peak_hours,
        'user_growth': user_growth,
        'total_users_count': total_users_count,
    }

def generate_analytics_csv_buffer(analytics_data):
    """Generates sanitized CSV report protecting against formula injection."""
    output = io.StringIO()
    writer = csv.writer(output)

    # Overview
    writer.writerow(["BookMySeat Business Analytics Report"])
    writer.writerow(["Filter Period", f"{analytics_data['start_date'].strftime('%Y-%m-%d')} to {analytics_data['end_date'].strftime('%Y-%m-%d')}"])
    writer.writerow([])
    writer.writerow(["Key Performance Indicator", "Value"])
    writer.writerow(["Gross Revenue (INR)", sanitize_csv_cell(f"{analytics_data['gross_revenue']:.2f}")])
    writer.writerow(["Total Refunded (INR)", sanitize_csv_cell(f"{analytics_data['total_refunded']:.2f}")])
    writer.writerow(["Net Revenue (INR)", sanitize_csv_cell(f"{analytics_data['net_revenue']:.2f}")])
    writer.writerow(["Total Bookings Processed", sanitize_csv_cell(analytics_data['total_bookings_count'])])
    writer.writerow(["Cancellations Count", sanitize_csv_cell(analytics_data['cancellation_count'])])
    writer.writerow(["Cancellation Rate (%)", sanitize_csv_cell(f"{analytics_data['cancellation_rate']}%")])
    writer.writerow(["Total Registered Users", sanitize_csv_cell(analytics_data['total_users_count'])])
    writer.writerow([])

    # Daily Revenue Breakdown
    writer.writerow(["Daily Revenue Breakdown"])
    writer.writerow(["Date", "Revenue (INR)", "Bookings Count"])
    for d in analytics_data['rev_by_day']:
        writer.writerow([
            sanitize_csv_cell(d['period'].strftime('%Y-%m-%d')),
            sanitize_csv_cell(f"{d['total']:.2f}"),
            sanitize_csv_cell(d['count'])
        ])
    writer.writerow([])

    # Most Booked Movies
    writer.writerow(["Top Performing Movies"])
    writer.writerow(["Movie Name", "Tickets Sold", "Revenue Generated (INR)"])
    for m in analytics_data['most_booked_movies']:
        writer.writerow([
            sanitize_csv_cell(m.name),
            sanitize_csv_cell(m.tickets_sold),
            sanitize_csv_cell(f"{m.revenue:.2f}" if m.revenue else "0.00")
        ])
    writer.writerow([])

    # Top Performing Theatres
    writer.writerow(["Top Performing Theatres"])
    writer.writerow(["Theatre Name", "City", "Tickets Sold", "Revenue (INR)"])
    for t in analytics_data['top_theaters']:
        writer.writerow([
            sanitize_csv_cell(t.name),
            sanitize_csv_cell(t.city),
            sanitize_csv_cell(t.tickets_sold),
            sanitize_csv_cell(f"{t.revenue:.2f}" if t.revenue else "0.00")
        ])

    output.seek(0)
    return output.getvalue().encode('utf-8')
