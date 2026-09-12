import razorpay
from app.core.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))