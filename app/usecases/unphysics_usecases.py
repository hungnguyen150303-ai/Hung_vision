# app/usecases/unphysics_usecases.py
from __future__ import annotations
from typing import Dict, Any, Optional
import logging

from app.configs.settings import settings
from app.hardware.rgb_camera import OpenCVCamera
from app.plugins.unphysics_engine import UnphysicsEngine

log = logging.getLogger("vision.uc.unphysics")

def start_unphysics_uc(service, *, settings=settings, overrides: Optional[Dict[str, Any]] = None):
    # FIX cứng 640x480@30 và thiết bị RGB từ settings (đã set 640x480)
    cam = OpenCVCamera(
        device=getattr(settings, "UNPHYSICS_RGB_DEVICE", "/dev/video0"),
        width=getattr(settings, "UNPHYSICS_RGB_WIDTH", 640),
        height=getattr(settings, "UNPHYSICS_RGB_HEIGHT", 480),
        fps=getattr(settings, "UNPHYSICS_RGB_FPS", 30),
        use_mjpg=getattr(settings, "RGB_USE_MJPEG", True),
        buffer_size=getattr(settings, "RGB_BUFFERSIZE", 2),
    )

    # Engine không cần overrides — dùng default theo unphysics.py
    engine = UnphysicsEngine(config={
        "center_radius": 40,
        "pull_threshold": 70.0,
        "stop_frames_threshold": 12,
        "active_frames_threshold": 6,
        "gesture_cooldown_ms": 1100.0,
        "tip_stationary_threshold": 15.0,
        "tip_stationary_duration_ms": 150.0,
    })

    service.start(rs=cam, engine=engine)
    log.info(
        "Unphysics start | dev=%s %dx%d@%dfps | cooldown=1100ms | CENTER by stationary tip 150ms, pull=70px",
        getattr(settings, "UNPHYSICS_RGB_DEVICE", "/dev/video0"),
        getattr(settings, "UNPHYSICS_RGB_WIDTH", 640),
        getattr(settings, "UNPHYSICS_RGB_HEIGHT", 480),
        getattr(settings, "UNPHYSICS_RGB_FPS", 30),
    )
    return {"ok": True, "running": service.is_running()}

def stop_unphysics_uc(service):
    service.stop()
    return {"ok": True, "running": service.is_running()}

def status_unphysics_uc(service):
    st = service.status()
    st["ok"] = True
    return st
