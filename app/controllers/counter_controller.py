import logging
from fastapi import APIRouter, Body
from app.core.container import container
from app.configs.settings import settings
from app.usecases.counter_usecases import start_counter_uc, stop_counter_uc, status_uc
from app.schemas.counter import StartRequest, StatusResponse

log = logging.getLogger("vision.controller")
router = APIRouter(prefix="", tags=["counter"])

@router.post("/start_counter", response_model=StatusResponse)
def start_counter(payload: StartRequest = Body(default=None)):
    log.info("POST /start_counter payload=%s", payload.model_dump(exclude_none=True) if payload else {})
    # override settings (nếu có)
    if payload:
        for k, v in payload.model_dump(exclude_none=True).items():
            if hasattr(settings, k.upper()):
                setattr(settings, k.upper(), v)
            elif k == "model":
                settings.MODEL_PATH = v
    resp = start_counter_uc(container.counter, settings=settings)
    log.info("Counter started: %s", resp)
    return resp

@router.post("/stop_counter", response_model=StatusResponse)
def stop_counter():
    log.info("POST /stop_counter")
    resp = stop_counter_uc(container.counter)
    log.info("Counter stopped: %s", resp)
    return resp

@router.get("/status", response_model=StatusResponse)
def status():
    resp = status_uc(container.counter)
    log.debug("GET /status -> %s", resp)
    return resp
