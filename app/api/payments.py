import hmac
import hashlib
import json

import razorpay
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as redis

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.razorpay_client import client
from app.core.config import RAZORPAY_KEY_ID, RAZORPAY_WEBHOOK_SECRET
from app.api.deps import get_current_user
from app.models.core_models import (
    User, Event, Seat, Booking, SeatStatus, Payment, PaymentStatus
)
from app.schemas.payments import PaymentOrderCreate, PaymentOrderOut, PaymentVerify

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("/create-order", response_model=PaymentOrderOut)
async def create_order(
    order_in: PaymentOrderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    """
    Step 1: Create a Razorpay Order for a seat the user has already locked.
    """
    # 1. Confirm the seat is actually locked by THIS user (from your existing /bookings/lock flow)
    lock_key = f"seat_lock:{order_in.event_id}:{order_in.seat_id}"
    lock_owner = await redis_client.get(lock_key)
    if lock_owner is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seat is not locked. Please lock the seat before paying."
        )
    if str(lock_owner) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This seat is locked by another user."
        )

    # 2. Look up the event to get the price
    result = await db.execute(select(Event).where(Event.id == order_in.event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")

    # 3. Confirm the seat isn't already booked (race-condition guard)
    existing = await db.execute(
        select(Booking).where(
            Booking.event_id == order_in.event_id,
            Booking.seat_id == order_in.seat_id,
            Booking.status == SeatStatus.booked,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Seat already booked.")

    amount_in_paise = int(event.base_price * 100)

    # 4. Ask Razorpay to create the order
    razorpay_order = client.order.create({
        "amount": amount_in_paise,
        "currency": "INR",
        "payment_capture": 1,  # auto-capture payment immediately on success
    })

    # 5. Save our own Payment record so we can track/reconcile later
    new_payment = Payment(
        user_id=current_user.id,
        event_id=order_in.event_id,
        seat_id=order_in.seat_id,
        razorpay_order_id=razorpay_order["id"],
        amount=event.base_price,
        currency="INR",
        status=PaymentStatus.created,
    )
    db.add(new_payment)
    await db.commit()

    return PaymentOrderOut(
        order_id=razorpay_order["id"],
        amount=amount_in_paise,
        currency="INR",
        key_id=RAZORPAY_KEY_ID,
    )


@router.post("/verify", status_code=status.HTTP_200_OK)
async def verify_payment(
    verify_in: PaymentVerify,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    """
    Step 2: Frontend calls this right after Razorpay's checkout popup succeeds.
    We verify the cryptographic signature before trusting the payment.
    """
    # 1. Fetch our Payment row for this order
    result = await db.execute(
        select(Payment).where(Payment.razorpay_order_id == verify_in.razorpay_order_id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment order not found.")
    if payment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your payment.")
    if payment.status == PaymentStatus.paid:
        raise HTTPException(status_code=400, detail="Payment already verified.")

    # 2. Verify the signature — this is THE critical security step.
    #    It proves the payment_id genuinely came from Razorpay for this order,
    #    not from someone forging a request to your API.
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": verify_in.razorpay_order_id,
            "razorpay_payment_id": verify_in.razorpay_payment_id,
            "razorpay_signature": verify_in.razorpay_signature,
        })
    except razorpay.errors.SignatureVerificationError:
        payment.status = PaymentStatus.failed
        await db.commit()
        raise HTTPException(status_code=400, detail="Payment signature verification failed.")

    # 3. Signature is valid — mark payment as paid
    payment.status = PaymentStatus.paid
    payment.razorpay_payment_id = verify_in.razorpay_payment_id
    await db.flush()

    # 4. Double-check the seat wasn't booked by someone else in the meantime
    existing = await db.execute(
        select(Booking).where(
            Booking.event_id == payment.event_id,
            Booking.seat_id == payment.seat_id,
            Booking.status == SeatStatus.booked,
        )
    )
    if existing.scalar_one_or_none():
        await db.commit()
        raise HTTPException(
            status_code=409,
            detail="Seat was booked by someone else. Contact support for a refund."
        )

    # 5. NOW create the actual booking (only reachable after real payment)
    new_booking = Booking(
        user_id=current_user.id,
        event_id=payment.event_id,
        seat_id=payment.seat_id,
        payment_id=payment.id,
        status=SeatStatus.booked,
    )
    db.add(new_booking)
    await db.commit()
    await db.refresh(new_booking)

    # 6. Release the Redis seat lock — no longer needed
    lock_key = f"seat_lock:{payment.event_id}:{payment.seat_id}"
    await redis_client.delete(lock_key)

    return {"message": "Payment verified and booking confirmed.", "booking_id": new_booking.id}


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def razorpay_webhook(request: Request):
    """
    Step 3 (safety net): Razorpay calls this server-to-server whenever a
    payment event happens, independent of whether the frontend called /verify.
    This catches cases like the user closing the browser tab right after paying.
    """
    body = await request.body()
    received_signature = request.headers.get("X-Razorpay-Signature", "")

    # Verify this request genuinely came from Razorpay, not a random POST from anyone
    expected_signature = hmac.new(
        key=RAZORPAY_WEBHOOK_SECRET.encode(),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, received_signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    payload = json.loads(body)
    event_type = payload.get("event")

    # You can log/handle events here — e.g. auto-mark Payment as failed
    # if a payment.failed event arrives, even if /verify was never called.
    # Kept minimal here since /verify handles the main happy path.
    print(f"Received Razorpay webhook event: {event_type}")

    return {"status": "ok"}