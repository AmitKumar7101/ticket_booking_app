from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import DateTime
from typing import List, Optional

# --- Venue Schemas ---
class VenueCreate(BaseModel):
    name: str
    city: str
    total_rows: int  # e.g., 5 rows (A, B, C, D, E)
    total_cols: int  # e.g., 10 seats per row (1 to 10)

class VenueOut(BaseModel):
    id: int
    name: str
    city: str

    class Config:
        from_attributes = True

# --- Event Schemas ---
class EventCreate(BaseModel):
    venue_id: int
    title: str
    description: str
    start_time: datetime
    base_price: float

class EventOut(BaseModel):
    id: int
    venue_id: int
    title: str
    description: str
    start_time: datetime
    base_price: float

    class Config:
        from_attributes = True