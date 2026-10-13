from django.urls import path
from . import views
from . import api_views

urlpatterns = [
    # Core Web Views & Discovery
    path('', views.movie_list, name='movie_list'),
    path('<int:movie_id>/', views.movie_detail, name='movie_detail'),
    path('<int:movie_id>/theaters/', views.theater_list, name='theater_list'),

    # Booking & 2-Minute Seat Reservation Flow
    path('theater/<int:theater_id>/seats/book/', views.book_seats, name='book_seats'),
    path('theater/<int:theater_id>/summary/', views.booking_summary, name='booking_summary'),
    path('theater/<int:theater_id>/payment/', views.payment_process, name='payment_process'),
    path('confirmation/<str:booking_reference>/', views.booking_confirmation, name='booking_confirmation'),
    path('cancel/<str:booking_reference>/', views.cancel_booking, name='cancel_booking'),

    # PDF Tickets & QR Code Verification
    path('ticket/<str:booking_reference>/download/', views.download_ticket_pdf, name='download_ticket_pdf'),
    path('verify-ticket/<str:token>/', views.verify_ticket_qr, name='verify_ticket_qr'),

    # Reviews, Ratings & Reporting
    path('<int:movie_id>/review/', views.submit_or_edit_review, name='submit_or_edit_review'),
    path('review/<int:review_id>/report/', views.report_review, name='report_review'),

    # Payment Gateway Webhook
    path('payment/webhook/', views.payment_webhook, name='payment_webhook'),

    # Admin Dashboard & Business Analytics
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('dashboard/export-csv/', views.export_analytics_csv, name='export_analytics_csv'),
    path('dashboard/moderate-review/<int:review_id>/', views.moderate_review, name='moderate_review'),

    # Django REST Framework (DRF) APIs
    path('api/movies/', api_views.MovieListAPIView.as_view(), name='api_movie_list'),
    path('api/movies/<int:pk>/', api_views.MovieDetailAPIView.as_view(), name='api_movie_detail'),
    path('api/theaters/', api_views.TheaterListAPIView.as_view(), name='api_theater_list'),
    path('api/theaters/<int:pk>/', api_views.TheaterDetailAPIView.as_view(), name='api_theater_detail'),
    path('api/theaters/<int:theater_id>/seats/', api_views.SeatListAPIView.as_view(), name='api_seat_list'),
    path('api/bookings/', api_views.UserBookingsAPIView.as_view(), name='api_user_bookings'),
    path('api/calculate-price/', api_views.CalculatePriceAPIView.as_view(), name='api_calculate_price'),
]