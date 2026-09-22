import uuid
from sqlalchemy import String, Integer, ForeignKey, DateTime, Float, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from datetime import datetime, timezone
import enum
from app.core.database import Base

# --- add to core_models.py for payment ---
from typing import Optional

class PaymentStatus(str, enum.Enum):
    created = "created"   # order created, not yet paid
    paid = "paid"         # verified successful
    failed = "failed"     # payment failed or verification failed

class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id"))

    razorpay_order_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    amount: Mapped[float] = mapped_column(Float)       # in rupees
    currency: Mapped[str] = mapped_column(String, default="INR")
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.created)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )



# --- Enums for strict state management ---
class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"

class SeatStatus(str, enum.Enum):
    available = "available"
    booked = "booked"

class TicketStatus(str, enum.Enum):
    pending = "pending"   # booking confirmed, ticket email not sent yet
    sent = "sent"         # PDF generated and emailed
    failed = "failed"     # gave up after all retries (can be re-sent manually)
# --- Models ---
class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.user)

class Venue(Base):
    __tablename__ = "venues"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, index=True)
    city: Mapped[str] = mapped_column(String)
    
    events = relationship("Event", back_populates="venue")
    seats = relationship("Seat", back_populates="venue")

class Event(Base):
    __tablename__ = "events"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"))
    title: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[str] = mapped_column(String)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    base_price: Mapped[float] = mapped_column(Float)
    
    venue = relationship("Venue", back_populates="events")

class Seat(Base):
    __tablename__ = "seats"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"))
    seat_number: Mapped[str] = mapped_column(String) # e.g., A1, A2
    
    venue = relationship("Venue", back_populates="seats")

class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    seat_id: Mapped[int] = mapped_column(ForeignKey("seats.id"))
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))  # NEW

    status: Mapped[SeatStatus] = mapped_column(Enum(SeatStatus), default=SeatStatus.available)

    # --- ticket delivery tracking (async task processing) ---
    ticket_code: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=lambda: str(uuid.uuid4())
    )
    ticket_status: Mapped[TicketStatus] = mapped_column(
        Enum(TicketStatus),
        default=TicketStatus.pending,
        server_default=TicketStatus.pending.value,
    )
    ticket_queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ticket_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    booked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )