# BookMySeat — Full-Stack Movie Ticket Booking Platform

## Overview
**BookMySeat** is a full-stack movie-ticket-booking platform built on top of the instructor's original training repository ([djnago-bookmyshow-clone](https://github.com/BitHeadmr/djnago-bookmyshow-clone.git)). This project fulfills all internship requirements by extending the foundation with advanced movie browsing, interactive seat selection powered by React.js, server-side concurrency locking, complete multi-step booking flows, payment simulation, comprehensive Django REST Framework (DRF) APIs, and responsive design.

---

## 1. Project Architecture & Enhancements

### Original Training Base vs Internship Enhancements

| Feature Area | Original Training Project | Enhanced Internship Project |
| :--- | :--- | :--- |
| **Movie Browsing** | Basic list view with title and basic search. | Full search by title/cast/description, interactive genre & language filtering, and a dedicated **Movie Detail** page (`movie_detail`). |
| **Theatres & Showtimes** | Minimal list of showtimes. | Rich showtime cards with screen location, price tiers, amenities badges, and responsive layout. |
| **Seat Selection** | Static checkboxes without live subtotal or tier pricing. | **Interactive React.js Seat Map** with real-time price calculator (VIP, Premium, Standard tiers), visual cinema screen curve, responsive mobile support, and server validation. |
| **Booking Flow** | Abruptly booked seats on checkbox POST and redirected to profile. | **Full 6-Step Flow**: Movie Selection &rarr; Theatre/Showtime &rarr; Interactive Seat Selection &rarr; Itemized Booking Summary &rarr; Payment Simulation Sandbox &rarr; Verified Confirmation Ticket. |
| **Payment Simulation** | Completely missing. | Interactive payment sandbox with Credit Card, UPI / QR, Net Banking, and BookMySeat Wallet simulation, supporting both **Success** and **Failure / Cancellation** outcomes. |
| **Concurrency & Security** | Prone to race conditions and duplicate bookings. | Secured with `transaction.atomic()` and row-level locking (`select_for_update()`), preventing duplicate seat bookings. Strict user authorization checks prevent unauthorized ticket inspection. |
| **Booking History** | Displayed unlinked individual seat rows. | Cohesive grouped orders by unique `booking_reference`, showing status badges, total amount, ticket view/print, and cancellation capability. |
| **REST APIs** | None. | Full **Django REST Framework (DRF)** endpoints for movies, theatres, seats, price calculator, and user bookings under `/movies/api/`. |
| **Frontend Framework** | Bootstrap 4 + jQuery. | Preserved existing templates and introduced **React.js 18** embedded component for dynamic seat management without breaking SSR architecture. |
| **Database & Production** | Hardcoded Render database URL in source code. | 12-factor compliant: reads `DATABASE_URL` dynamically from environment with clean fallback to local SQLite; WhiteNoise static file serving; PostgreSQL ready. |

---

## 2. Complete Booking Flow

1. **Movie Selection (`/movies/`)**:
   - Browse movie cards displaying posters, IMDb-style ratings, genres, and languages.
   - Search by keyword or filter by genre pills (Action, Sci-Fi, Drama) and language.
   - Click "Details" for synopsis and cast, or "Book" to view showtimes.

2. **Theatre & Showtime Selection (`/movies/<id>/theaters/`)**:
   - View theatres screening the movie with location/hall info, timing, and base ticket prices.

3. **Seat Selection (`/movies/theater/<id>/seats/book/`)**:
   - Dynamic React.js seat map categorized into **VIP**, **Premium**, and **Standard** rows.
   - Instant live breakdown: selected count, ticket subtotal, convenience fees, GST, and total payable.
   - Server-side availability validation ensures no sold seats can be submitted.

4. **Booking Summary (`/movies/theater/<id>/summary/`)**:
   - Itemized order preview: screen date & time, seat numbers with tier pricing, convenience charges, taxes, and customer credentials.

5. **Payment Simulation Sandbox (`/movies/theater/<id>/payment/`)**:
   - Sandbox environment displaying prominent demo disclaimers.
   - Choose payment mode: Card, UPI, Net Banking, or Wallet.
   - Test "Pay (Simulate Success)" or "Simulate Failure" to verify error recovery.

6. **Booking Confirmation (`/movies/confirmation/<booking_reference>/`)**:
   - Displays confirmed E-Ticket with unique Reference ID (e.g., `BMS-8F92A1`).
   - Cinema entrance QR code visual, showtime, seat breakdown, and total paid.
   - One-click "Print / Save Ticket" layout optimized for browser printing (`Ctrl+P`).
   - Accessible only by the authenticated owner or staff.

---

## 3. Technology Stack

- **Backend**: Python 3.13, Django 5.1.x, Django REST Framework 3.15.x
- **Frontend**: Django Templates, React.js 18, Bootstrap 4, Font Awesome 5
- **Database**: SQLite (Local development) / PostgreSQL (Production via `dj-database-url`)
- **Static Assets & WSGI**: WhiteNoise, Gunicorn

---

## 4. REST API Documentation

All API endpoints are available under `/movies/api/`:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/movies/api/movies/` | List all movies with `?search=`, `?genre=`, `?language=` |
| `GET` | `/movies/api/movies/<id>/` | Retrieve single movie details |
| `GET` | `/movies/api/theaters/` | List theatres, filterable by `?movie_id=` |
| `GET` | `/movies/api/theaters/<id>/` | Retrieve theatre details and seat statistics |
| `GET` | `/movies/api/theaters/<id>/seats/` | Retrieve seat layout and availability for a theatre |
| `GET` | `/movies/api/bookings/` | Retrieve authenticated user's booking history |
| `POST` | `/movies/api/calculate-price/` | Calculate price breakdown given `{"seat_ids": [...]}` |

---

## 5. Local Setup Instructions

### Prerequisites
- Python 3.10+ (Tested on Python 3.13)
- Git

### Steps

1. **Clone the repository**:
   ```bash
   git clone https://github.com/BitHeadmr/djnago-bookmyshow-clone.git
   cd djnago-bookmyshow-clone
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv .venv
   # On Windows:
   .\.venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

5. **Run the automated test suite**:
   ```bash
   python manage.py test
   ```
   *(All 12 unit and integration tests should pass).*

6. **Start the local development server**:
   ```bash
   python manage.py runserver
   ```
   Open your browser at `http://127.0.0.1:8000/`.

---

## 6. Deployment Guidelines

### Environment Variables
Configure the following in your hosting provider (Render, Vercel, Railway, etc.):

- `SECRET_KEY`: A strong random string for production.
- `DEBUG`: `False` (for production) or `True` (for testing).
- `ALLOWED_HOSTS`: `.vercel.app,.onrender.com,localhost,127.0.0.1`
- `DATABASE_URL`: PostgreSQL connection string (e.g., `postgresql://user:password@host/dbname`). If omitted, falls back to SQLite.

### Deployment on Vercel
1. The project includes a configured `vercel.json` pointing to `bookmyseat/wsgi.py`.
2. Connect your GitHub repository to Vercel.
3. Add the environment variables above.
4. Deploy!

### Deployment on Render / Railway
1. A `Procfile` is included: `web: gunicorn bookmyseat.wsgi:application`.
2. Static assets are automatically served via WhiteNoise (`STATIC_ROOT = BASE_DIR / 'staticfiles'`).
3. Set Build Command: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`.
4. Set Start Command: `gunicorn bookmyseat.wsgi:application`.

---

## 7. Automated Testing Results

Run tests anytime with:
```bash
python manage.py test
```

Test coverage includes:
- `test_movie_list_and_search`: Movie browsing and search queries.
- `test_movie_filter_by_genre_and_language`: Filtering by categories.
- `test_movie_detail_view`: Detailed view loading and content.
- `test_theater_list_view`: Theatre list for selected movie.
- `test_seat_selection_requires_login`: Authentication guard on booking views.
- `test_seat_selection_and_summary_flow`: End-to-end selection and summary transition.
- `test_prevent_booking_already_booked_seat`: Server validation rejecting already booked seats.
- `test_payment_simulation_success`: Complete atomic booking and confirmation generation.
- `test_payment_simulation_failure_does_not_book_seats`: Error handling leaving seats unreserved.
- `test_user_cannot_access_other_users_booking_confirmation`: Cross-user authorization protection (403 Forbidden).
- `test_cancel_booking_releases_seat`: Booking cancellation and seat availability restoration.
- `test_drf_api_endpoints`: Verification of DRF serializers and endpoints.
