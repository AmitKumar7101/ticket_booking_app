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
from app.services.ticket_queue import enqueue_ticket_email
from app.core.rate_limit import rate_limit_by_user



router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("/create-order", response_model=PaymentOrderOut,dependencies=[Depends(rate_limit_by_user(
        "create-order", capacity=10, refill_rate=10 / 60, user_dependency=get_current_user
    ))],
)
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

async def finalize_successful_payment(
    db: AsyncSession,
    redis_client: redis.Redis,
    payment: Payment,
) -> Booking | None:
    """
    Shared finalization logic used by both /verify and the webhook.

    Marks the payment paid and creates the Booking, but is safe to call
    more than once for the same payment (idempotent) and safe to call
    from a genuine race between /verify and the webhook.

    Returns the Booking on success, or None if the seat was genuinely
    booked under a DIFFERENT payment in the meantime (real conflict).
    """
    # Idempotency: this payment is already fully processed.
    if payment.status == PaymentStatus.paid:
        existing = await db.execute(
            select(Booking).where(Booking.payment_id == payment.id)
        )
        return existing.scalar_one_or_none()

    # Idempotency: did THIS payment already produce a booking (e.g. webhook
    # got here first) even though the status field hasn't caught up yet?
    own = await db.execute(
        select(Booking).where(Booking.payment_id == payment.id)
    )
    own_booking = own.scalar_one_or_none()
    if own_booking:
        payment.status = PaymentStatus.paid
        await db.commit()
        return own_booking

    # Real conflict: the seat is booked, but under a DIFFERENT payment.
    conflict = await db.execute(
        select(Booking).where(
            Booking.event_id == payment.event_id,
            Booking.seat_id == payment.seat_id,
            Booking.status == SeatStatus.booked,
        )
    )
    if conflict.scalar_one_or_none():
        payment.status = PaymentStatus.failed
        await db.commit()
        return None

    # Happy path: mark paid and create the booking.
    payment.status = PaymentStatus.paid
    new_booking = Booking(
        user_id=payment.user_id,
        event_id=payment.event_id,
        seat_id=payment.seat_id,
        payment_id=payment.id,
        status=SeatStatus.booked,
    )
    db.add(new_booking)
    await db.commit()
    await db.refresh(new_booking)

    lock_key = f"seat_lock:{payment.event_id}:{payment.seat_id}"
    await redis_client.delete(lock_key)

    # Hand the heavy work (PDF + QR + email) to the Celery worker. Never raises:
    # if RabbitMQ is down the sweeper re-queues this booking later.
    await enqueue_ticket_email(new_booking.id)

    return new_booking




@router.post("/verify", status_code=status.HTTP_200_OK,dependencies=[Depends(rate_limit_by_user(
        "verify", capacity=10, refill_rate=10 / 60, user_dependency=get_current_user
    ))],  # 10 / min)
    )
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

    # If the webhook already finalized this payment before we got here,
    # don't error - just return the existing booking (idempotent success).
    if payment.status == PaymentStatus.paid:
        existing_booking = await db.execute(
            select(Booking).where(Booking.payment_id == payment.id)
        )
        existing_booking = existing_booking.scalar_one_or_none()
        return {
            "message": "Payment already verified and booking confirmed.",
            "booking_id": existing_booking.id if existing_booking else None,
        }

    # 2. Verify the signature - this is THE critical security step.
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

    # 3. Signature is valid - record the payment id, then delegate to the
    #    shared finalizer (also used by the webhook) to avoid duplicating
    #    the booking-creation / conflict-check logic.
    payment.razorpay_payment_id = verify_in.razorpay_payment_id

    booking = await finalize_successful_payment(db, redis_client, payment)

    if booking is None:
        raise HTTPException(
            status_code=409,
            detail="Seat was booked by someone else. Contact support for a refund."
        )

    return {"message": "Payment verified and booking confirmed.", "booking_id": booking.id}


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
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
    entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = entity.get("order_id")

    # Always return 200 for events we deliberately skip - Razorpay retries
    # with backoff on non-2xx responses, and we don't want retry storms.
    if not order_id:
        return {"status": "ignored"}

    result = await db.execute(
        select(Payment).where(Payment.razorpay_order_id == order_id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        return {"status": "ignored"}

    if event_type == "payment.captured":
        payment.razorpay_payment_id = entity.get("id")
        await finalize_successful_payment(db, redis_client, payment)

    elif event_type == "payment.failed" and payment.status == PaymentStatus.created:
        payment.status = PaymentStatus.failed
        await db.commit()
        lock_key = f"seat_lock:{payment.event_id}:{payment.seat_id}"
        await redis_client.delete(lock_key)

    return {"status": "ok"}