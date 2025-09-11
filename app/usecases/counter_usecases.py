# app/usecases/counter_usecases.py
from __future__ import annotations

from typing import Dict, Any, Optional
import logging

from ultralytics import YOLO
from app.configs.settings import settings
from app.hardware.rgb_camera import OpenCVCamera

log = logging.getLogger("vision.uc.counter")


def start_counter_uc(service, *, settings=settings, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Khởi động COUNTER với camera RGB (2D).
    """
    o = overrides or {}

    # --- RGB camera ---
    cam = OpenCVCamera(
        device=o.get("rgb_device", getattr(settings, "RGB_CAM_DEVICE", 0)),
        width=o.get("rgb_width", getattr(settings, "RGB_CAM_WIDTH", 1280)),
        height=o.get("rgb_height", getattr(settings, "RGB_CAM_HEIGHT", 720)),
        fps=o.get("rgb_fps", getattr(settings, "RGB_CAM_FPS", 30)),
    )

    # --- YOLO model ---
    weights = o.get("yolo_weights", getattr(settings, "COUNTER_YOLO_WEIGHTS", "yolo11s.pt"))
    yolo_model = YOLO(weights)

    # --- Params ---
    camera_side = o.get("camera_side", getattr(settings, "COUNTER_CAMERA_SIDE", "left"))
    line_x = float(o.get("line_x", getattr(settings, "COUNTER_LINE_X", 0.5)))

    enter_window = float(o.get("enter_window", getattr(settings, "COUNTER_ENTER_WINDOW", 1.0)))
    log_interval = float(o.get("log_interval", getattr(settings, "COUNTER_LOG_INTERVAL", 2.0)))
    min_dist = float(o.get("min_dist", getattr(settings, "COUNTER_MIN_DIST", 0.2)))
    max_dist = float(o.get("max_dist", getattr(settings, "COUNTER_MAX_DIST", 6.0)))

    # NOTE: không truyền 'conf' / 'device' vì CounterService.start không hỗ trợ
    service.start(
        rs_wrapper=cam,
        yolo_wrapper=yolo_model,
        camera_side=camera_side,
        line_x_ratio=line_x,
        use_depth=False,
        min_dist=min_dist,
        max_dist=max_dist,
        enter_window=enter_window,
        log_interval=log_interval,
    )

    log.info("Counter requested start | side=%s line=%.2f (RGB cam)", camera_side, line_x)
    return {"ok": True, "running": service.is_running()}


def stop_counter_uc(service) -> Dict[str, Any]:
    service.stop()
    return {"ok": True, "running": service.is_running()}


def status_uc(service) -> Dict[str, Any]:
    st = service.status()
    st["ok"] = True
    return st


__all__ = ["start_counter_uc", "stop_counter_uc", "status_uc"]
