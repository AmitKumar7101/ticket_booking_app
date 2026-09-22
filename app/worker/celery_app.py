"""Celery application (RabbitMQ broker). Shared by the API (publisher) and the worker."""
from celery import Celery

from app.core.config import CELERY_BROKER_URL

TICKET_TASK_NAME = "tickets.generate_and_send"
REQUEUE_TASK_NAME = "tickets.requeue_stale"

celery_app = Celery(
    "ticket_booking",
    broker=CELERY_BROKER_URL,
    include=["app.worker.tasks"],  # only imported by the worker, not by the API
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,          # we track state in Postgres, no result backend needed
    timezone="UTC",
    enable_utc=True,
    task_default_queue="tickets",     # durable queue; messages are persistent by default
    # Reliability: ack only after the task finishes, so a crashed worker doesn't lose the task
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    # Fail fast when publishing from the API if RabbitMQ is down (the sweeper catches up later)
    broker_connection_timeout=3,
    task_publish_retry=True,
    task_publish_retry_policy={
        "max_retries": 1,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.5,
    },
    # Safety net: re-queue bookings whose ticket never got sent (needs `celery beat`)
    beat_schedule={
        "requeue-stale-tickets": {
            "task": REQUEUE_TASK_NAME,
            "schedule": 600.0,  # every 10 minutes
        },
    },
)