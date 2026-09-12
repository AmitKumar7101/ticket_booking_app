# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth
from app.api import admin, bookings, events,payments

from app.seed_admin import create_super_admin
from app.core.redis import init_redis, close_redis
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_super_admin()
    await init_redis()
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

@app.get("/")
async def root():
    return {"message": "Welcome to the Ticket Booking API"}