"""API-side helper that pushes a 'send ticket' job onto RabbitMQ via Celery."""
import asyncio
import logging

from app.worker.celery_app import TICKET_TASK_NAME, celery_app

logger = logging.getLogger(__name__)


async def enqueue_ticket_email(booking_id: int) -> bool:
    """
    Publish the ticket job. Never raises: if RabbitMQ is unreachable we log and return
    False, and the periodic sweeper will pick the booking up later. A paid booking must
    never fail just because the queue is down.
    """

    def _publish() -> None:
        # send_task by name -> the API process doesn't need to import PDF/email code
        celery_app.send_task(TICKET_TASK_NAME, args=[booking_id])

    try:
        await asyncio.to_thread(_publish)  # kombu is blocking; keep the event loop free
        return True
    except Exception:
        logger.exception(
            "Could not enqueue ticket email for booking %s; the sweeper will retry.", booking_id
        )
        return False