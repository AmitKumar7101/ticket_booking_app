from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.api.deps import require_admin
from app.models.core_models import User, Venue, Seat, Event
from app.schemas.admin import VenueCreate, VenueOut, EventCreate, EventOut

router = APIRouter(prefix="/admin", tags=["Admin"])

@router.post("/venues", response_model=VenueOut, status_code=status.HTTP_201_CREATED)
async def create_venue(
    venue_in: VenueCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a venue and automatically batch-generates seats based on rows and columns (e.g., A1-A10, B1-B10).
    """
    # 1. Create the Venue
    new_venue = Venue(name=venue_in.name, city=venue_in.city)
    db.add(new_venue)
    await db.flush()  # Flush to populate new_venue.id without committing the transaction yet

    # 2. Batch-generate Seats (Row Letters A-Z, Col Numbers 1-N)
    seats_to_create = []
    for r in range(venue_in.total_rows):
        row_letter = chr(65 + r)  # 65 is ASCII for 'A'
        for c in range(1, venue_in.total_cols + 1):
            seat_code = f"{row_letter}{c}"
            seats_to_create.append(
                Seat(venue_id=new_venue.id, seat_number=seat_code)
            )

    db.add_all(seats_to_create)
    await db.commit()
    await db.refresh(new_venue)
    return new_venue


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    event_in: EventCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Schedules an event attached to a specific venue.
    """
    # 1. Validate that the venue exists
    result = await db.execute(select(Venue).where(Venue.id == event_in.venue_id))
    venue = result.scalar_one_or_none()
    if not venue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Venue with id {event_in.venue_id} does not exist."
        )

    # 2. Create the Event
    new_event = Event(
        venue_id=event_in.venue_id,
        title=event_in.title,
        description=event_in.description,
        start_time=event_in.start_time,
        base_price=event_in.base_price
    )
    db.add(new_event)
    await db.commit()
    await db.refresh(new_event)
    return new_event