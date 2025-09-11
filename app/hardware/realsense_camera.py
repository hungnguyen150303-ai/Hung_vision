# app/hardware/realsense_camera.py
from __future__ import annotations
import time
from typing import Optional, Tuple

import numpy as np

try:
    import pyrealsense2 as rs
    _RS_OK = True
except Exception:
    rs = None
    _RS_OK = False

class RealSenseCamera:
    """
    Wrapper RealSense 3D chuẩn cho services.
    get_frames() -> (color_bgr: np.ndarray | None, depth_frame | None)
    """
    kind: str = "3D"

    def __init__(self, width: int = 640, height: int = 480, fps: int = 30):
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.pipe: Optional["rs.pipeline"] = None
        self.align: Optional["rs.align"] = None

    @staticmethod
    def list_devices() -> list:
        if not _RS_OK:
            return []
        ctx = rs.context()
        return [d.get_info(rs.camera_info.serial_number) for d in ctx.query_devices()]

    def open(self):
        if not _RS_OK:
            return
        if self.pipe is not None:
            return
        cfg = rs.config()
        cfg.enable_stream(rs.stream.depth, self.width, self.height, rs.format.z16, self.fps)
        cfg.enable_stream(rs.stream.color, self.width, self.height, rs.format.bgr8, self.fps)
        self.pipe = rs.pipeline()
        self.pipe.start(cfg)
        self.align = rs.align(rs.stream.color)

    def is_opened(self) -> bool:
        return self.pipe is not None

    def get_frames(self) -> Tuple[Optional[np.ndarray], Optional[object]]:
        if not self.pipe:
            self.open()
        if not self.pipe:
            return None, None
        frames = self.pipe.wait_for_frames()
        if self.align:
            frames = self.align.process(frames)
        depth = frames.get_depth_frame()
        color = frames.get_color_frame()
        if not color:
            return None, None
        color_np = np.asanyarray(color.get_data())
        return color_np, depth

    read = get_frames

    def check_connectivity(self, timeout_s: float = 1.5) -> Tuple[bool, str]:
        if not _RS_OK:
            return False, "pyrealsense2 chưa sẵn sàng (chưa cài hoặc driver lỗi)"
        devs = self.list_devices()
        if not devs:
            return False, "Không tìm thấy thiết bị RealSense nào"
        t0 = time.time()
        self.open()
        if not self.is_opened():
            return False, "Không mở được pipeline RealSense"
        while time.time() - t0 < timeout_s:
            color, depth = self.get_frames()
            if color is not None:
                h, w = color.shape[:2]
                return True, f"ĐÃ KẾT NỐI camera 3D RealSense ({w}x{h}@{self.fps}fps, serials={devs})"
            time.sleep(0.01)
        return False, "Không nhận được khung hình từ RealSense trong thời gian chờ"

    def stop(self):
        self.close()

    def close(self):
        if self.pipe is not None:
            try:
                self.pipe.stop()
            except Exception:
                pass
        self.pipe = None
        self.align = None
