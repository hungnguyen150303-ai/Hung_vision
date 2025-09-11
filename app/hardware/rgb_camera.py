# app/hardware/rgb_camera.py
from __future__ import annotations
import cv2, threading, time
from typing import Optional, Tuple, Union

class OpenCVCamera:
    """
    Nguồn camera 2D (RGB). Trả về (color_bgr, None) để tương thích service.
    Hỗ trợ device index (0,1,...) hoặc đường dẫn '/dev/videoX'.
    """
    kind: str = "2D"

    def __init__(self, device: Union[int, str] = 0, width: int = 640, height: int = 480, fps: int = 30,
                 use_mjpg: bool = True, buffer_size: int = 2):
        self.device = device
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.use_mjpg = bool(use_mjpg)
        self.buffer_size = int(buffer_size)
        self.cap: Optional[cv2.VideoCapture] = None
        self._lock = threading.RLock()

    def _to_index(self, dev: Union[int, str]) -> Union[int, str]:
        if isinstance(dev, str) and dev.startswith("/dev/video"):
            try:
                return int(dev.replace("/dev/video", ""))
            except Exception:
                return dev
        return dev

    def open(self):
        with self._lock:
            if self.cap is not None:
                return
            dev_idx = self._to_index(self.device)

            # thử CAP_V4L2 trước
            self.cap = cv2.VideoCapture(dev_idx, cv2.CAP_V4L2)
            if not self.cap or not self.cap.isOpened():
                # fallback CAP_ANY
                self.cap = cv2.VideoCapture(dev_idx)

            if not self.cap or not self.cap.isOpened():
                self.cap = None
                return

            # set props (best-effort)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
            if self.use_mjpg:
                try:
                    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
                    self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)
                except Exception:
                    pass
            try:
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, max(1, self.buffer_size))
            except Exception:
                pass

    def get_frames(self) -> Tuple[Optional["np.ndarray"], None]:
        import numpy as np  # lazy import
        with self._lock:
            if self.cap is None:
                self.open()
            if self.cap is None:
                return None, None
            ok, frame = self.cap.read()
            if not ok or frame is None:
                time.sleep(0.002)
                return None, None
            return frame, None

    read = get_frames

    def is_opened(self) -> bool:
        with self._lock:
            return bool(self.cap and self.cap.isOpened())

    def check_connectivity(self, timeout_s: float = 1.5) -> Tuple[bool, str]:
        """
        Thử mở và đọc 1 frame trong timeout.
        Trả về (ok, message).
        """
        t0 = time.time()
        self.open()
        if not self.is_opened():
            return False, f"Không mở được camera RGB (device={self.device})"
        while time.time() - t0 < timeout_s:
            frame, _ = self.get_frames()
            if frame is not None:
                h, w = frame.shape[:2]
                return True, f"ĐÃ KẾT NỐI camera 2D RGB ({w}x{h}@{self.fps}fps, dev={self.device})"
            time.sleep(0.01)
        return False, "Không nhận được khung hình từ camera RGB trong thời gian chờ"

    def stop(self):
        self.close()

    def close(self):
        with self._lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
