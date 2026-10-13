from django.urls import path
from . import views
from . import api_views

urlpatterns = [
    # Web views
    path('', views.movie_list, name='movie_list'),
    path('<int:movie_id>/', views.movie_detail, name='movie_detail'),
    path('<int:movie_id>/theaters/', views.theater_list, name='theater_list'),
    path('theater/<int:theater_id>/seats/book/', views.book_seats, name='book_seats'),
    path('theater/<int:theater_id>/summary/', views.booking_summary, name='booking_summary'),
    path('theater/<int:theater_id>/payment/', views.payment_process, name='payment_process'),
    path('confirmation/<str:booking_reference>/', views.booking_confirmation, name='booking_confirmation'),
    path('cancel/<str:booking_reference>/', views.cancel_booking, name='cancel_booking'),

    # REST APIs (DRF)
    path('api/movies/', api_views.MovieListAPIView.as_view(), name='api_movie_list'),
    path('api/movies/<int:pk>/', api_views.MovieDetailAPIView.as_view(), name='api_movie_detail'),
    path('api/theaters/', api_views.TheaterListAPIView.as_view(), name='api_theater_list'),
    path('api/theaters/<int:pk>/', api_views.TheaterDetailAPIView.as_view(), name='api_theater_detail'),
    path('api/theaters/<int:theater_id>/seats/', api_views.SeatListAPIView.as_view(), name='api_seat_list'),
    path('api/bookings/', api_views.UserBookingsAPIView.as_view(), name='api_user_bookings'),
    path('api/calculate-price/', api_views.CalculatePriceAPIView.as_view(), name='api_calculate_price'),
]