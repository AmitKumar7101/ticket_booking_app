from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.core.database import get_db
from app.models.core_models import Event, Seat
from app.schemas.booking import EventCatalogOut, SeatOut

router = APIRouter(prefix="/events", tags=["Catalog"])


@router.get("", response_model=List[EventCatalogOut])
async def get_events(db: AsyncSession = Depends(get_db)):
    """
    Fetch the catalog of all scheduled events.
    """
    result = await db.execute(select(Event))
    events = result.scalars().all()
    return events


@router.get("/{event_id}/seats", response_model=List[SeatOut])
async def get_event_seats(event_id: int, db: AsyncSession = Depends(get_db)):
    """
    Fetch the seat map for a specific event.
    """
    # 1. Fetch the event to identify where it is being held
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with ID {event_id} does not exist."
        )

    # 2. Fetch all seats associated with that specific venue
    seats_result = await db.execute(select(Seat).where(Seat.venue_id == event.venue_id))
    seats = seats_result.scalars().all()

    return seats