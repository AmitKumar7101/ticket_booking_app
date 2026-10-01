# 🎟️ Ticket Booking API

An asynchronous backend for booking event tickets. Users browse events, hold a seat, pay online through Razorpay, and receive a PDF ticket with a QR code by email. Ticket delivery runs in a background worker, so a slow or failing email service never blocks or breaks a paid booking.

## Features

- **Authentication and roles**: JWT login and signup, bcrypt password hashing, and admin-only endpoints (role-based access control).
- **Event catalog**: admins create venues (seats are auto-generated from rows and columns) and schedule events. Anyone can browse events and seat maps.
- **Double-booking protection**: a seat is held for 5 minutes using an atomic Redis lock (`SET NX EX`) before payment. A booking is created only after payment succeeds.
- **Razorpay payments**: server-side order creation, HMAC signature verification, and a webhook as a safety net for users who close the tab after paying.
- **Idempotent finalization**: `/payments/verify` and the webhook share one finalizer, so duplicate or racing callbacks produce exactly one booking.
- **Rate limiting**: a Redis token-bucket limiter implemented as an atomic Lua script. It limits by IP on public endpoints and by user on authenticated ones, and fails open if Redis is unavailable.
- **Async ticket delivery**: Celery workers on RabbitMQ generate a PDF ticket with a QR code and email it over SMTP. Tasks use late acknowledgement and exponential-backoff retries. A Celery Beat job re-queues stuck tickets every 10 minutes.
- **Ticket endpoints**: download the PDF on demand (generated in memory, nothing stored on disk) and re-send the email with a 60-second cooldown.
- **Database migrations**: managed with Alembic.

## Tech stack

| Area | Technology |
|---|---|
| API | FastAPI, Uvicorn |
| Database | PostgreSQL, SQLAlchemy (async), asyncpg, Alembic |
| Cache and locks | Redis |
| Payments | Razorpay |
| Background jobs | Celery, RabbitMQ |
| Tickets | ReportLab (PDF), qrcode (QR) |
| Auth | python-jose (JWT), passlib and bcrypt |

## How a booking works

```
1. POST /bookings/lock          -> Redis holds the seat for 5 minutes
2. POST /payments/create-order  -> checks the lock, creates a Razorpay order
3. Razorpay checkout (frontend) -> user pays
4. POST /payments/verify        -> signature check, booking created
   POST /payments/webhook       -> same finalizer, runs if /verify never arrives
5. Celery task                  -> builds the PDF + QR, emails the ticket
6. Celery Beat (every 10 min)   -> re-queues tickets that were never sent
```

## Project structure

```
app/
├── api/          # Route handlers: auth, admin, events, bookings, payments, tickets
├── core/         # Config, DB engine, Redis, rate limiter, security, Razorpay client
├── models/       # SQLAlchemy models
├── schemas/      # Pydantic request and response schemas
├── services/     # Ticket data, PDF/QR generation, email sender, queue helper
├── worker/       # Celery app and tasks
├── main.py       # FastAPI entry point
└── seed_admin.py # Creates the initial admin user on startup
alembic/          # Database migrations
```

## API overview

| Method | Endpoint | Access | Description |
|---|---|---|---|
| POST | `/auth/signup` | Public | Register and receive a token |
| POST | `/auth/login` | Public | Log in and receive a token |
| GET | `/events` | Public | List events |
| GET | `/events/{event_id}/seats` | Public | Seat map for an event |
| POST | `/bookings/lock` | User | Hold a seat for 5 minutes |
| POST | `/payments/create-order` | User | Create a Razorpay order |
| POST | `/payments/verify` | User | Verify payment and confirm booking |
| POST | `/payments/webhook` | Razorpay | Server-to-server payment events |
| GET | `/bookings/{booking_id}/ticket` | User | Download the ticket PDF |
| POST | `/bookings/{booking_id}/resend-ticket` | User | Re-queue the ticket email |
| POST | `/admin/venues` | Admin | Create a venue and generate its seats |
| POST | `/admin/events` | Admin | Schedule an event |

Interactive docs are available at `http://localhost:8000/docs` once the server is running.

## Getting started

### Prerequisites

- Python 3.10+
- PostgreSQL
- Redis
- RabbitMQ
- A Razorpay account (test mode is fine)
- An SMTP account for sending emails

### Installation

```bash
git clone https://github.com/<your-username>/ticket_booking.git
cd ticket_booking

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root:

```env
# Razorpay
RAZORPAY_KEY_ID=your_key_id
RAZORPAY_KEY_SECRET=your_key_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret

# RabbitMQ (Celery broker)
CELERY_BROKER_URL=amqp://guest:guest@localhost:5672//

# SMTP (ticket emails)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=you@example.com
SMTP_PASSWORD=your_smtp_password
SMTP_STARTTLS=true
SMTP_USE_SSL=false
SMTP_FROM_EMAIL=you@example.com
SMTP_FROM_NAME=Ticket Booking

# Misc
TICKET_TIMEZONE=Asia/Kolkata
TRUST_X_FORWARDED_FOR=false   # true only behind a trusted reverse proxy
```

The PostgreSQL URL is set in `app/core/database.py`, the Redis URL in `app/core/redis.py`, and the JWT secret in `app/core/security.py`. Update them for your environment. Moving them into `.env` is recommended before deploying.

### Set up the database

```bash
alembic upgrade head
```

### Run the services

Run each of these in its own terminal:

```bash
# 1. API server
uvicorn app.main:app --reload

# 2. Celery worker (on Windows add: --pool=solo)
celery -A app.worker.celery_app worker -Q tickets --loglevel=info

# 3. Celery Beat (re-queues unsent tickets)
celery -A app.worker.celery_app beat --loglevel=info
```

On first startup an admin user is created by `app/seed_admin.py`. Change its credentials before deploying anywhere public.

### Razorpay webhook

Point a Razorpay webhook at `POST /payments/webhook` and subscribe to the `payment.captured` and `payment.failed` events. Use the same secret you set as `RAZORPAY_WEBHOOK_SECRET`. For local testing, expose your server with a tunnel such as ngrok.

## Design notes

- **Why lock first, book after payment?** Seats are held in Redis with a TTL, so abandoned checkouts free themselves. The database only stores confirmed bookings.
- **Why both `/verify` and a webhook?** `/verify` gives the user instant feedback. The webhook covers closed tabs and dropped connections. Both call the same idempotent function.
- **Why a message queue for tickets?** PDF generation and SMTP are slow and can fail. Moving them to Celery keeps the payment response fast, and the retry and sweeper logic means a paid booking always gets its ticket eventually.
- **Why fail open on rate limiting?** A Redis outage should not take down logins and bookings. Protection is lost only for the length of the outage.

## Possible improvements

- Automated tests (pytest) for the payment and locking flows
- Refund handling for the "paid but seat taken" conflict case
- Docker Compose setup for Postgres, Redis, and RabbitMQ
- Restrict CORS origins and move all secrets to environment variables
- A QR scanner endpoint for entry validation
