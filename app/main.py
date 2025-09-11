from fastapi import FastAPI
from app.core.lifecycle import register_lifecycle
from app.controllers.counter_controller import router as counter_router
from app.utils.logging import configure_logging

# Khởi tạo logging ngay khi import
_log = configure_logging()
_log.info("Starting FastAPI app...")

def create_app():
    app = FastAPI(title="Vision Counter Service", version="1.0.0")
    register_lifecycle(app)
    app.include_router(counter_router)
    return app

app = create_app()
