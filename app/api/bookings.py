from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as redis
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.core_models import User, Event, Seat, Booking, SeatStatus
from app.schemas.booking import BookingCreate, BookingOut
from app.core.redis import get_redis
from pydantic import BaseModel



router = APIRouter(prefix="/bookings", tags=["Bookings"])


class SeatLockRequest(BaseModel):
    event_id: int
    seat_id: int
# old booking endpoint new endpoint is the payemnts create order
# @router.post("", response_model=BookingOut, status_code=status.HTTP_201_CREATED)
# async def create_booking(
#         booking_in: BookingCreate,
#         current_user: User = Depends(get_current_user),
#         db: AsyncSession = Depends(get_db)
# ):
#     """
#     Reserve a seat for a specific event.
#
#     """
#
#     stmt = (
#         select(Seat)
#         .join(Event, Event.venue_id == Seat.venue_id)
#         .where(
#             Seat.id == booking_in.seat_id,
#             Event.id == booking_in.event_id
#         )
#         .with_for_update()
#     )
#
#     result = await db.execute(stmt)
#     seat_result = result
#     #  Verify the seat exists
#
#     if not seat_result.scalar_one_or_none():
#         raise HTTPException(status_code=404, detail="Seat not found.")
#
#     # 1. Verify the event exists
#     event_result = await db.execute(select(Event).where(Event.id == booking_in.event_id))
#     if not event_result.scalar_one_or_none():
#         raise HTTPException(status_code=404, detail="Event not found.")
#
#
#
#     # 3. Check if the seat is already booked for this event
#     existing_booking = await db.execute(
#             select(Booking).where(
#                 Booking.event_id == booking_in.event_id,
#                 Booking.seat_id == booking_in.seat_id,
#                 Booking.status == SeatStatus.booked
#             )
#         )
#     if existing_booking.scalar_one_or_none():
#         raise HTTPException(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 detail="Seat is already booked for this event."
#         )
#
#     # 4. Create the booking record
#     new_booking = Booking(
#         user_id=current_user.id,
#         event_id=booking_in.event_id,
#         seat_id=booking_in.seat_id,
#         status=SeatStatus.booked
#     )
#
#     db.add(new_booking)
#     await db.commit()
#
#
#     await db.refresh(new_booking)
#     return new_booking


@router.post("/lock", status_code=status.HTTP_200_OK)
async def lock_seat(
        request: SeatLockRequest,
        current_user: User = Depends(get_current_user),
        redis_client: redis.Redis = Depends(get_redis)
):
    """
    Temporarily holds a seat for 5 minutes using Redis.
    """
    lock_key = f"seat_lock:{request.event_id}:{request.seat_id}"

    # Atomic SET NX EX command
    lock_acquired = await redis_client.set(
        name=lock_key,
        value=str(current_user.id),
        ex=300,
        nx=True
    )

    if not lock_acquired:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This seat is currently held by another user."
        )

    return {
        "message": "Seat successfully held.",
        "status": "locked",
        "countdown_timer_seconds": 300
    }