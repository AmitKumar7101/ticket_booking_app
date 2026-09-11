# app/main.py
from fastapi import FastAPI
from app.api import auth
from app.api import admin,bookings,events

from app.seed_admin import create_super_admin
from app.core.redis import init_redis, close_redis
app = FastAPI(title="AI-Powered Ticket Booking API")
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_super_admin()
    await init_redis()
    yield
    await close_redis()

app = FastAPI(lifespan=lifespan)
# Include routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(events.router)
app.include_router(bookings.router)

@app.get("/")
async def root():
    return {"message": "Welcome to the Ticket Booking API"}