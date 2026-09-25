# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth
from app.api import admin, bookings, events,payments

from app.seed_admin import create_super_admin
from app.core.redis import init_redis, close_redis
from app.core.rate_limit import TokenBucket
from app.core.config import TRUST_X_FORWARDED_FOR
from contextlib import asynccontextmanager
from app.api import admin, bookings, events, payments, tickets   # add `tickets`


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_super_admin()
    await init_redis()

    from app.core.redis import redis_client  # fetched after init_redis() sets it
    app.state.rate_limiter = TokenBucket(redis_client)
    app.state.trust_x_forwarded_for = TRUST_X_FORWARDED_FOR


    yield
    await close_redis()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(events.router)
app.include_router(bookings.router)
app.include_router(payments.router)
app.include_router(tickets.router) 

@app.get("/")
async def root():
    return {"message": "Welcome to the Ticket Booking API"}