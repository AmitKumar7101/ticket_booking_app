"""Ticket data access shared by the API (download endpoint) and the Celery worker."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core_models import Booking, Event, Payment, Seat, User, Venue


@dataclass(frozen=True)
class TicketData:
    booking_id: int
    user_id: int
    ticket_code: str
    attendee_email: str
    event_title: str
    venue_name: str
    venue_city: str
    start_time: datetime
    seat_number: str
    amount: float
    currency: str
    payment_ref: Optional[str]


async def load_ticket_data(db: AsyncSession, booking_id: int) -> Optional[TicketData]:
    """Load everything needed to render a ticket for one booking (None if not found)."""
    stmt = (
        select(Booking, User, Event, Venue, Seat, Payment)
        .select_from(Booking)
        .join(User, User.id == Booking.user_id)
        .join(Event, Event.id == Booking.event_id)
        .join(Venue, Venue.id == Event.venue_id)
        .join(Seat, Seat.id == Booking.seat_id)
        .join(Payment, Payment.id == Booking.payment_id)
        .where(Booking.id == booking_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None

    booking, user, event, venue, seat, payment = row
    return TicketData(
        booking_id=booking.id,
        user_id=user.id,
        ticket_code=booking.ticket_code,
        attendee_email=user.email,
        event_title=event.title,
        venue_name=venue.name,
        venue_city=venue.city,
        start_time=event.start_time,
        seat_number=seat.seat_number,
        amount=payment.amount,
        currency=payment.currency,
        payment_ref=payment.razorpay_payment_id,
    )