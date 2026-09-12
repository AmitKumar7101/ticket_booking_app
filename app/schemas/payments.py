from pydantic import BaseModel

class PaymentOrderCreate(BaseModel):
    event_id: int
    seat_id: int

class PaymentOrderOut(BaseModel):
    order_id: str
    amount: int          # amount in paise (Razorpay requires paise, not rupees)
    currency: str
    key_id: str           # public key id, safe to expose to frontend

class PaymentVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str