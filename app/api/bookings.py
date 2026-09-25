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
from app.core.rate_limit import rate_limit_by_user


router = APIRouter(prefix="/bookings", tags=["Bookings"])


class SeatLockRequest(BaseModel):
    event_id: int
    seat_id: int


@router.post("/lock", status_code=status.HTTP_200_OK,
              dependencies=[Depends(rate_limit_by_user(
        "lock", capacity=10, refill_rate=10 / 60,
              user_dependency=get_current_user
                ))],  # 10 / min
    )
async def lock_seat(
        request: SeatLockRequest,
        current_user: User = Depends(get_current_user),
        redis_client: redis.Redis = Depends(get_redis),

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