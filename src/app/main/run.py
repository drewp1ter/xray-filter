from fastapi import FastAPI
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.lib.db import init_database
from .proxies import router as proxies_router, get_online_proxies

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(get_online_proxies, "interval", seconds=3600)
    scheduler.start()
    yield
    scheduler.shutdown()

def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.include_router(proxies_router)
    init_database()
    return app
