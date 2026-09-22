"""Ticket endpoints: download the PDF (regenerated on demand) and re-send the email."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.core_models import Booking, TicketStatus, User
from app.services.ticket_pdf import build_ticket_pdf
from app.services.ticket_queue import enqueue_ticket_email
from app.services.tickets import load_ticket_data

router = APIRouter(prefix="/bookings", tags=["Tickets"])

RESEND_COOLDOWN = timedelta(seconds=60)


@router.get("/{booking_id}/ticket")
async def download_ticket(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate the ticket PDF on the fly (nothing is stored on disk)."""
    ticket = await load_ticket_data(db, booking_id)
    # 404 (not 403) for other people's bookings, so booking ids can't be probed
    if ticket is None or ticket.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")

    pdf_bytes = await asyncio.to_thread(build_ticket_pdf, ticket)  # CPU-bound, keep off the loop
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="ticket-{booking_id}.pdf"'},
    )


@router.post("/{booking_id}/resend-ticket", status_code=status.HTTP_202_ACCEPTED)
async def resend_ticket(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue the ticket email again (e.g. it went to spam, or delivery had failed)."""
    booking = await db.get(Booking, booking_id)
    if booking is None or booking.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found.")

    now = datetime.now(timezone.utc)
    if booking.ticket_queued_at and now - booking.ticket_queued_at < RESEND_COOLDOWN:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A ticket email was queued moments ago. Please wait a minute and try again.",
        )

    booking.ticket_status = TicketStatus.pending
    booking.ticket_queued_at = now
    await db.commit()

    if not await enqueue_ticket_email(booking.id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ticket queue is temporarily unavailable. It will be retried automatically.",
        )
    return {"message": "Ticket email queued."}