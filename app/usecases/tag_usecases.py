# app/usecases/tag_usecases.py
from __future__ import annotations
from typing import Optional, Dict, Any
import logging

from app.configs.settings import settings
from app.hardware.rgb_camera import OpenCVCamera
from app.plugins.tag_engine import TagEngine, TagEngineConfig

log = logging.getLogger("vision.uc.tag")

def start_tag_uc(service, *, settings=settings, overrides: Optional[Dict[str, Any]] = None):
    # 2D RGB @ 640x480
    cam = OpenCVCamera(
        device=getattr(settings, "TAG_RGB_DEVICE", 0),
        width=getattr(settings, "TAG_RGB_WIDTH", 640),
        height=getattr(settings, "TAG_RGB_HEIGHT", 480),
        fps=getattr(settings, "TAG_RGB_FPS", 30),
        use_mjpg=getattr(settings, "RGB_USE_MJPEG", True),
        buffer_size=getattr(settings, "RGB_BUFFERSIZE", 2),
    )

    cfg = TagEngineConfig(
        calib_file=getattr(settings, "TAG_CALIB_FILE", "/app/models/camera_calib2.npz"),
        tag_size_m=float(getattr(settings, "TAG_SIZE_M", 0.135)),
        family=getattr(settings, "TAG_FAMILY", "tag36h11"),
        nthreads=int(getattr(settings, "TAG_NTHREADS", 2)),
        quad_decimate=float(getattr(settings, "TAG_QUAD_DECIMATE", 1.0)),
        quad_sigma=float(getattr(settings, "TAG_QUAD_SIGMA", 0.0)),
        refine_edges=int(getattr(settings, "TAG_REFINE_EDGES", 1)),
        decode_sharpening=float(getattr(settings, "TAG_DECODE_SHARPENING", 0.25)),
        alpha_pos=float(getattr(settings, "TAG_ALPHA_POS", 0.25)),
        alpha_dist=float(getattr(settings, "TAG_ALPHA_DIST", 0.25)),
        alpha_angle=float(getattr(settings, "TAG_ALPHA_ANGLE", 0.25)),
    )
    engine = TagEngine(cfg)

    service.start(rs=cam, engine=engine)
    log.info("tagdata start | dev=%s %dx%d@%dfps | calib=%s | size=%.3fm | family=%s",
             getattr(settings, "TAG_RGB_DEVICE", 0),
             getattr(settings, "TAG_RGB_WIDTH", 640),
             getattr(settings, "TAG_RGB_HEIGHT", 480),
             getattr(settings, "TAG_RGB_FPS", 30),
             cfg.calib_file, cfg.tag_size_m, cfg.family)
    return {"ok": True, "running": service.is_running()}

def stop_tag_uc(service):
    service.stop()
    return {"ok": True, "running": service.is_running()}

def status_tag_uc(service):
    st = service.status()
    st["ok"] = True
    return st
