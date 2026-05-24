from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.lib.db import init_database
from .proxies import router as proxies_router

scheduler = AsyncIOScheduler()


def create_app() -> FastAPI:
    app = FastAPI()
    app.include_router(proxies_router)
    init_database()
    return app
