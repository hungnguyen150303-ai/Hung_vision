# app/usecases/followme_usecases.py
from __future__ import annotations
import logging
from typing import Dict, Any
import pyrealsense2 as rs
from app.services.followme_service import FollowMeService
from app.plugins.followme_engine import FollowMeEngine

log = logging.getLogger("vision.usecases.followme")

class RSAlignWrapper:
    def __init__(self, width=640, height=480, fps=30):
        self.pipe = rs.pipeline()
        cfg = rs.config()
        cfg.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
        cfg.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)
        self.align = rs.align(rs.stream.color)
        self.pipe.start(cfg)

    def get_frames(self):
        frames = self.pipe.wait_for_frames()
        frames = self.align.process(frames)
        depth = frames.get_depth_frame()
        color = frames.get_color_frame()
        if not depth or not color:
            return None, depth
        import numpy as np
        img = None
        try:
            img = np.asanyarray(color.get_data())
        except Exception:
            img = None
        return img, depth

    def stop(self):
        try:
            self.pipe.stop()
        except Exception:
            pass

def start_followme_uc(service: FollowMeService, *, settings, overrides: Dict[str, Any] | None = None) -> Dict[str, Any]:
    o = overrides or {}
    rsw = RSAlignWrapper(
        width=int(o.get("rs_width", getattr(settings, "RS_WIDTH", 640))),
        height=int(o.get("rs_height", getattr(settings, "RS_HEIGHT", 480))),
        fps=int(o.get("rs_fps", getattr(settings, "RS_FPS", 30))),
    )
    engine = FollowMeEngine(config={
        "yolo_weights": o.get("yolo_weights", getattr(settings, "YOLO_MODEL", "yolo11s.pt")),
        "yolo_conf":    float(o.get("yolo_conf", 0.5)),
        "recognition_range_m": float(o.get("FOLLOWME_RECOG_RANGE_M", 2.5)),
        "face_distance_thr":   float(o.get("FOLLOWME_FACE_THR", 0.40)),
        "register_confirm_frames": int(o.get("FOLLOWME_REG_CONFIRM", 11)),
        "follow_confirm_frames":   int(o.get("FOLLOWME_FOLLOW_CONFIRM", 10)),
        "pause_confirm_frames":    int(o.get("FOLLOWME_PAUSE_CONFIRM", 5)),
    })
    service.start(rsw, engine, **o)
    st = service.status(); st["ok"]=True; st["method"]="follow_me"
    return st

def stop_followme_uc(service: FollowMeService) -> Dict[str, Any]:
    service.stop()
    st = service.status(); st["ok"]=True; st["method"]="follow_me"
    return st

def status_followme_uc(service: FollowMeService) -> Dict[str, Any]:
    st = service.status(); st["ok"]=True; st["method"]="follow_me"
    return st
