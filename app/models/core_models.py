from sqlalchemy import String, Integer, ForeignKey, DateTime, Float, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from datetime import datetime, timezone
import enum
from app.core.database import Base

# --- Enums for strict state management ---
class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"

class SeatStatus(str, enum.Enum):
    available = "available"
    booked = "booked"

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
    status: Mapped[SeatStatus] = mapped_column(Enum(SeatStatus), default=SeatStatus.available)
    booked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )