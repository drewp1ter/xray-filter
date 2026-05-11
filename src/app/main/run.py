from fastapi import FastAPI
from .proxies import router as proxies_router

def create_app() -> FastAPI:
    app = FastAPI()
    app.include_router(proxies_router)
    return app
