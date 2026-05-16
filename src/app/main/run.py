from fastapi import FastAPI
from app.db import init_database
from .proxies import router as proxies_router

def create_app() -> FastAPI:
    app = FastAPI()
    app.include_router(proxies_router)
    init_database()
    return app
