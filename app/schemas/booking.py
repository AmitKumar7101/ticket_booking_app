from pydantic import BaseModel
from datetime import datetime
from typing import List
from app.models.core_models import SeatStatus


# --- Catalog Browsing Schemas ---
class EventCatalogOut(BaseModel):
    id: int
    venue_id: int
    title: str
    description: str
    start_time: datetime
    base_price: float

    class Config:
        from_attributes = True


class SeatOut(BaseModel):
    id: int
    seat_number: str

    class Config:
        from_attributes = True


# --- Booking Schemas ---
class BookingCreate(BaseModel):
    event_id: int
    seat_id: int


class BookingOut(BaseModel):
    id: int
    user_id: int
    event_id: int
    seat_id: int
    status: SeatStatus
    booked_at: datetime

    class Config:
        from_attributes = True