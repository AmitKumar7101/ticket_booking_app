# app/core/config.py
import os
from dotenv import load_dotenv

load_dotenv()  # reads a local .env file during development

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# --- Message queue (Celery + RabbitMQ) ---
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//")

# --- Ticket email (SMTP) ---
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_STARTTLS = _env_bool("SMTP_STARTTLS", True)
SMTP_USE_SSL = _env_bool("SMTP_USE_SSL", False)
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Ticket Booking")

# Timezone used when printing event times on tickets and in emails
TICKET_TIMEZONE = os.getenv("TICKET_TIMEZONE", "Asia/Kolkata")