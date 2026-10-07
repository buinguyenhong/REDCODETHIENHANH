import sys
import os
import asyncio

# Ensure backend root is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, Base
from app.seed import seed_database

async def main():
    print("Synchronizing database schema...")
    async with engine.begin() as conn:
        from app.config import settings
        if settings.ENVIRONMENT in ('development', 'test'):
            await conn.run_sync(Base.metadata.create_all)
    print("Seeding database...")
    await seed_database()
    print("Database ready!")

if __name__ == "__main__":
    asyncio.run(main())
