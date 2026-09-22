"""Celery tasks: build the ticket PDF (with QR code) and email it after a booking."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import DATABASE_URL
from app.models.core_models import Booking, TicketStatus
from app.services.email_sender import send_ticket_email
from app.services.ticket_pdf import build_ticket_pdf
from app.services.tickets import TicketData, load_ticket_data
from app.worker.celery_app import REQUEUE_TASK_NAME, TICKET_TASK_NAME, celery_app

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_BASE_SECONDS = 30            # backoff: 30s, 60s, 120s, 240s, 480s (~15.5 min total)
STALE_AFTER = timedelta(minutes=20)  # must be longer than the full retry window above
SWEEP_BATCH = 100


@asynccontextmanager
async def _session():
    """
    Celery tasks are synchronous, so each DB step runs in its own asyncio.run().
    A pooled engine is bound to one event loop, so we use a throwaway NullPool engine
    per call instead of the API's global engine.
    """
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


async def _load_if_pending(booking_id: int) -> Optional[TicketData]:
    async with _session() as db:
        booking = await db.get(Booking, booking_id)
        if booking is None:
            logger.warning("Booking %s not found; dropping task.", booking_id)
            return None
        if booking.ticket_status == TicketStatus.sent:
            logger.info("Ticket for booking %s already sent; skipping.", booking_id)
            return None
        return await load_ticket_data(db, booking_id)


async def _set_status(booking_id: int, new_status: TicketStatus) -> None:
    values: dict = {"ticket_status": new_status}
    if new_status == TicketStatus.sent:
        values["ticket_sent_at"] = datetime.now(timezone.utc)
    async with _session() as db:
        await db.execute(update(Booking).where(Booking.id == booking_id).values(**values))
        await db.commit()


@celery_app.task(bind=True, name=TICKET_TASK_NAME, max_retries=MAX_RETRIES)
def generate_and_send_ticket(self, booking_id: int) -> None:
    """Idempotent: safe to run more than once for the same booking."""
    try:
        ticket = asyncio.run(_load_if_pending(booking_id))
        if ticket is None:
            return
        pdf_bytes = build_ticket_pdf(ticket)
        send_ticket_email(ticket, pdf_bytes)
        asyncio.run(_set_status(booking_id, TicketStatus.sent))
        logger.info("Ticket sent for booking %s.", booking_id)
    except Exception as exc:
        attempt = self.request.retries
        if attempt >= self.max_retries:
            logger.exception(
                "Ticket for booking %s failed permanently after %s attempts.", booking_id, attempt + 1
            )
            asyncio.run(_set_status(booking_id, TicketStatus.failed))
            return
        countdown = RETRY_BASE_SECONDS * (2 ** attempt)
        logger.warning(
            "Ticket for booking %s failed (attempt %s): %s. Retrying in %ss.",
            booking_id, attempt + 1, exc, countdown,
        )
        raise self.retry(exc=exc, countdown=countdown)


async def _claim_stale() -> list[int]:
    """Find bookings stuck in 'pending' and stamp them so the next sweep skips them."""
    now = datetime.now(timezone.utc)
    cutoff = now - STALE_AFTER
    async with _session() as db:
        result = await db.execute(
            select(Booking.id)
            .where(
                Booking.ticket_status == TicketStatus.pending,
                Booking.booked_at < cutoff,
                or_(Booking.ticket_queued_at.is_(None), Booking.ticket_queued_at < cutoff),
            )
            .order_by(Booking.id)
            .limit(SWEEP_BATCH)
        )
        ids = list(result.scalars())
        if ids:
            await db.execute(
                update(Booking).where(Booking.id.in_(ids)).values(ticket_queued_at=now)
            )
            await db.commit()
        return ids


@celery_app.task(name=REQUEUE_TASK_NAME)
def requeue_stale_tickets() -> int:
    """Periodic safety net (run by `celery beat`) for tickets that were never queued or lost."""
    ids = asyncio.run(_claim_stale())
    for booking_id in ids:
        generate_and_send_ticket.delay(booking_id)
    if ids:
        logger.info("Re-queued %s stale ticket(s): %s", len(ids), ids)
    return len(ids)