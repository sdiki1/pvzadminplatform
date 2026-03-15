import asyncio

from app.db.session import init_db


async def main() -> None:
    await init_db()
    print("DB initialized")


if __name__ == "__main__":
    asyncio.run(main())
