# app/plugins/tag_engine.py
from __future__ import annotations
import math, logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, List

import cv2
import numpy as np

log = logging.getLogger("vision.tag.engine")

try:
    from pupil_apriltags import Detector
    _AT_OK = True
except Exception:
    _AT_OK = False
    Detector = None
    log.warning("Không tìm thấy pupil_apriltags. Hãy thêm 'pupil-apriltags' vào requirements.txt")

def _load_scaled_intrinsics(npz_path: str, out_size: Tuple[int,int]) -> Tuple[np.ndarray, np.ndarray]:
    """Đọc K, dist từ file calib npz và scale theo kích thước ảnh thực tế."""
    data = np.load(npz_path)
    K = data["K"].astype(np.float32)
    dist = data["dist"].astype(np.float32)
    w0, h0 = data["img_size"]
    sx, sy = out_size[0] / float(w0), out_size[1] / float(h0)
    K2 = K.copy()
    K2[0,0] *= sx; K2[1,1] *= sy
    K2[0,2] *= sx; K2[1,2] *= sy
    return K2, dist

def _ema(prev, new, alpha):
    if prev is None: return new
    return prev*(1-alpha) + new*alpha

def _wrap_pi(a):
    return (a + math.pi) % (2*math.pi) - math.pi

@dataclass
class TagEngineConfig:
    calib_file: str
    tag_size_m: float = 0.135
    family: str = "tag36h11"
    nthreads: int = 2
    quad_decimate: float = 1.0
    quad_sigma: float = 0.0
    refine_edges: int = 1
    decode_sharpening: float = 0.25
    # smoothing
    alpha_pos: float = 0.25
    alpha_dist: float = 0.25
    alpha_angle: float = 0.25

class TagEngine:
    """
    Tính pose CAM trong hệ quy chiếu TAG (TAG là gốc (0,0), mặt hướng xuống trên map).
    Events trả về:
      - {"state": "tag_found"|"tag_lost"}
      - {"detect": {"id":int, "family":str, "x":m, "y":m, "angle":rad, "distance":m}}
    """
    def __init__(self, cfg: TagEngineConfig):
        self.cfg = cfg
        self.detector = None
        self._had_tag = False
        self._x = None; self._y = None; self._D = None; self._ang = None
        if _AT_OK:
            self.detector = Detector(
                families=cfg.family,
                nthreads=cfg.nthreads,
                quad_decimate=cfg.quad_decimate,
                quad_sigma=cfg.quad_sigma,
                refine_edges=cfg.refine_edges,
                decode_sharpening=cfg.decode_sharpening,
            )
            log.info("AprilTag Detector ready: family=%s", cfg.family)
        else:
            log.warning("AprilTag Detector unavailable (pupil_apriltags missing).")

        self._K = None
        self._fxfycc = None  # tuple (fx,fy,cx,cy)

    def _ensure_intrinsics(self, frame_shape: Tuple[int,int,int]):
        if self._fxfycc is not None: return
        h, w = frame_shape[:2]
        try:
            K, dist = _load_scaled_intrinsics(self.cfg.calib_file, (w, h))
            self._K = K
            self._fxfycc = (float(K[0,0]), float(K[1,1]), float(K[0,2]), float(K[1,2]))
            log.info("Load calib ok: fx=%.1f fy=%.1f cx=%.1f cy=%.1f (from %s)",
                     self._fxfycc[0], self._fxfycc[1], self._fxfycc[2], self._fxfycc[3], self.cfg.calib_file)
        except Exception as e:
            self._K = None
            self._fxfycc = None
            log.warning("Không tải được calib %s: %s. Sẽ detect không pose.", self.cfg.calib_file, e)

    def step(self, color_bgr: Optional[np.ndarray]) -> List[Dict[str,Any]]:
        evs: List[Dict[str,Any]] = []
        if color_bgr is None or not isinstance(color_bgr, np.ndarray) or self.detector is None:
            if self._had_tag:
                self._had_tag = False
                evs.append({"state":"tag_lost"})
            return evs

        h, w = color_bgr.shape[:2]
        self._ensure_intrinsics(color_bgr.shape)

        # tiền xử lý nhẹ để ổn định
        gray = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(2.0, (8,8))
        gray = clahe.apply(gray)
        blur = cv2.GaussianBlur(gray, (0,0), 1.0)
        sharp = cv2.addWeighted(gray, 1.6, blur, -0.6, 0)

        # detect
        if self._fxfycc is not None:
            dets = self.detector.detect(
                sharp, estimate_tag_pose=True,
                camera_params=self._fxfycc, tag_size=self.cfg.tag_size_m
            )
        else:
            dets = self.detector.detect(sharp, estimate_tag_pose=False)

        if not dets:
            if self._had_tag:
                self._had_tag = False
                evs.append({"state":"tag_lost"})
            return evs

        # chọn tag lớn nhất để ổn định
        best = max(dets, key=lambda d: cv2.contourArea(np.array(d.corners, dtype=np.float32)))

        # nếu có pose:
        if hasattr(best, "pose_R") and best.pose_R is not None and hasattr(best, "pose_t"):
            R_tc = best.pose_R.astype(np.float32)           # TAG->CAM
            t_tc = best.pose_t.reshape(3,1).astype(np.float32)
            R_ct = R_tc.T
            C_t = -R_ct @ t_tc      # tọa độ CAM trong hệ TAG

            x_m = float(C_t[0,0])                  # ngang phải
            z_m = float(C_t[2,0])
            y_m = -z_m                              # dọc xuống (map)
            D = math.sqrt(x_m*x_m + y_m*y_m + float(C_t[1,0])**2)

            # góc lệch giữa hướng TAG-down (0,+1) và hướng CAM->TAG
            yaw = math.atan2(x_m, y_m)
            angle = _wrap_pi(-yaw)

            # smoothing
            self._x = _ema(self._x, x_m, self.cfg.alpha_pos)
            self._y = _ema(self._y, y_m, self.cfg.alpha_pos)
            self._D = _ema(self._D, D,  self.cfg.alpha_dist)
            self._ang = _ema(self._ang, angle, self.cfg.alpha_angle)

            payload = {
                "id": int(getattr(best, "tag_id", -1)),
                "family": getattr(best, "tag_family", self.cfg.family),
                "x": float(self._x),
                "y": float(self._y),
                "angle": float(self._ang),     # rad
                "distance": float(self._D),    # m
            }
        else:
            # không có pose -> chỉ trả id/family
            payload = {
                "id": int(getattr(best, "tag_id", -1)),
                "family": getattr(best, "tag_family", self.cfg.family),
            }

        if not self._had_tag:
            evs.append({"state":"tag_found"})
            self._had_tag = True

        evs.append({"detect": payload})
        return evs
