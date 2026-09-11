import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.core_models import User, UserRole

async def create_super_admin():
    async with AsyncSessionLocal() as db:
        # Define the admin credentials
        admin_email = "admin@ticketbooking.com"
        admin_password = "SuperSecretPassword123!"

        # Check if a super admin already exists
        result = await db.execute(
            select(User).where(User.email == admin_email)
        )
        existing_admin = result.scalar_one_or_none()

        if existing_admin:
            # print(f"Super admin already exists for: {admin_email}. Skipping creation.")
            return

        # Hash the password using our bcrypt utility
        hashed_password = get_password_hash(admin_password)

        # Create the user and explicitly assign the admin role
        super_admin = User(
            email=admin_email,
            hashed_password=hashed_password,
            role=UserRole.admin
        )

        try:
            db.add(super_admin)
            await db.commit()
            print(f"Success! Super admin account created for: {admin_email}")
        except Exception as e:
            await db.rollback()
            print("Error creating admin account.")
            print(f"Details: {e}")

if __name__ == "__main__":
    # Run the asynchronous function
    asyncio.run(create_super_admin())