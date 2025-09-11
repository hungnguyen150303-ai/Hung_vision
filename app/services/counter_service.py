# app/services/counter_service.py
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
from collections import deque

import numpy as np

from app.mqtt.client import mqtt_bus

log = logging.getLogger("vision.counter")


# -----------------------------
# Tracker tối giản theo centroid
# -----------------------------
@dataclass
class Track:
    id: int
    bbox: Tuple[int, int, int, int]
    last_seen: float
    history: deque
    side: str
    counted_in: bool
    counted_out: bool


class CentroidTracker:
    def __init__(self, max_distance: float = 80.0, max_age: float = 1.2):
        self.next_id = 1
        self.tracks: Dict[int, Track] = {}
        self.max_distance = max_distance
        self.max_age = max_age

    @staticmethod
    def _centroid(b):
        x1, y1, x2, y2 = b
        return (int((x1 + x2) / 2), int((y1 + y2) / 2))

    def update(self, detections: List[Tuple[int, int, int, int]]):
        now = time.time()
        det_centroids = [self._centroid(b) for b in detections]
        unmatched_dets = set(range(len(detections)))

        # match theo nearest-neighbor
        for tid in sorted(self.tracks.keys(), key=lambda i: -self.tracks[i].last_seen):
            tr = self.tracks[tid]
            tcx, tcy = self._centroid(tr.bbox)
            best_j = -1
            best_dist = 1e9
            for j in list(unmatched_dets):
                dcx, dcy = det_centroids[j]
                dist = np.hypot(tcx - dcx, tcy - dcy)
                if dist < best_dist:
                    best_dist = dist
                    best_j = j
            if best_j != -1 and best_dist <= self.max_distance:
                tr.bbox = detections[best_j]
                tr.last_seen = now
                tr.history.append(self._centroid(tr.bbox))
                if len(tr.history) > 20:
                    tr.history.popleft()
                unmatched_dets.remove(best_j)

        # tạo track mới cho det chưa match
        for j in unmatched_dets:
            b = detections[j]
            tr = Track(
                id=self.next_id,
                bbox=b,
                last_seen=now,
                history=deque([self._centroid(b)], maxlen=20),
                side='unknown',
                counted_in=False,
                counted_out=False,
            )
            self.tracks[self.next_id] = tr
            self.next_id += 1

        # xóa track quá già
        to_del = [tid for tid, tr in self.tracks.items() if now - tr.last_seen > self.max_age]
        for tid in to_del:
            del self.tracks[tid]

        return self.tracks


# -----------------------------
# Helper vào/ra
# -----------------------------
def get_side(x_cen: int, line_x: int) -> str:
    return 'left' if x_cen < line_x else 'right'


def is_inside(side: str, camera_side: str) -> bool:
    # camera_side = 'left' nghĩa là camera đặt bên trái cửa nhìn vào,
    # nên "inside" là phía đối diện đường line
    if camera_side == 'left':
        return side == 'right'
    else:
        return side == 'left'


# -----------------------------
# CounterService
# -----------------------------
class CounterService:
    """
    - Nhận rs wrapper (get_frames -> (color, depth)) và yolo wrapper (detect_person(frame))
    - Đếm vào/ra theo crossing line, publish MQTT ngay khi có sự kiện:
        topic: vision/result
        payload:
          {"type":"detect","payload":{"method":"counter","data":{"action":"IN"}}}
          {"type":"detect","payload":{"method":"counter","data":{"action":"OUT"}}}
    - Log định kỳ tổng IN/OUT theo log_interval.
    - Có camera lock để không tranh chấp giữa các service.
    """

    def __init__(self) -> None:
        # runtime
        self.thread: Optional[threading.Thread] = None
        self.stop_evt = threading.Event()
        self.running = False

        # deps
        self.rs = None        # RealSense wrapper
        self.yolo = None      # YOLO wrapper

        # config
        self.camera_side = 'left'
        self.line_x_ratio = 0.5
        self.use_depth = False
        self.min_dist = 0.2
        self.max_dist = 6.0
        self.enter_window = 1.0
        self.log_interval = 2.0

        # state
        self.tracker = CentroidTracker()
        self.total_in = 0
        self.total_out = 0
        self.enter_times = deque()
        self.last_multi_log_ts = 0.0
        self.last_summary_ts = 0.0

        # camera lock
        self._cam_lock = None
        self._lock_acquired = False

    # ---------- Lock DI ----------
    def set_camera_lock(self, lock):
        self._cam_lock = lock

    def _release_camera_lock(self):
        if self._cam_lock and self._lock_acquired:
            try:
                self._cam_lock.release()
            except RuntimeError:
                pass
            self._lock_acquired = False
            time.sleep(0.2)  # grace cho driver nhả hẳn

    # ---------- Public API ----------
    def is_running(self) -> bool:
        return bool(self.running)

    def start(
        self,
        rs_wrapper,
        yolo_wrapper,
        *,
        camera_side: str = 'left',
        line_x_ratio: float = 0.5,
        use_depth: bool = False,
        min_dist: float = 0.2,
        max_dist: float = 6.0,
        enter_window: float = 1.0,
        log_interval: float = 2.0,
    ) -> None:
        if self.running:
            log.info("Counter already running.")
            return

        # acquire camera lock
        if self._cam_lock and not self._cam_lock.acquire(blocking=False):
            log.warning("Camera is busy by another service.")
            return
        self._lock_acquired = True

        try:
            self.rs = rs_wrapper
            self.yolo = yolo_wrapper

            self.camera_side = str(camera_side or 'left').lower()
            self.line_x_ratio = float(line_x_ratio)
            self.use_depth = bool(use_depth)
            self.min_dist = float(min_dist)
            self.max_dist = float(max_dist)
            self.enter_window = float(enter_window)
            self.log_interval = float(log_interval)

            # reset state
            self.tracker = CentroidTracker()
            self.total_in = 0
            self.total_out = 0
            self.enter_times.clear()
            self.last_multi_log_ts = 0.0
            self.last_summary_ts = 0.0

            self.stop_evt.clear()
            self.thread = threading.Thread(target=self._loop, name="counter-loop", daemon=True)
            self.thread.start()
            self.running = True

            log.info(
                "Counter START | camera_side=%s line_x_ratio=%.2f use_depth=%s dist=[%.2f..%.2f] enter_window=%.1fs",
                self.camera_side, self.line_x_ratio, self.use_depth, self.min_dist, self.max_dist, self.enter_window
            )
        except Exception:
            self._release_camera_lock()
            raise

    def stop(self) -> None:
        if not self.running:
            return
        self.stop_evt.set()
        try:
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=3.0)
        finally:
            self._cleanup()
            self.running = False
            self._release_camera_lock()
            log.info("Counter STOP | SUMMARY: IN=%d OUT=%d", self.total_in, self.total_out)

    def status(self) -> Dict[str, object]:
        return {
            "running": self.running,
            "camera_side": self.camera_side,
            "line_x_ratio": self.line_x_ratio,
            "use_depth": self.use_depth,
            "min_dist": self.min_dist,
            "max_dist": self.max_dist,
            "enter_window": self.enter_window,
            "log_interval": self.log_interval,
            "total_in": self.total_in,
            "total_out": self.total_out,
        }

    # ---------- Internals ----------
    def _cleanup(self):
        try:
            if self.rs is not None:
                if hasattr(self.rs, "close"):
                    self.rs.close()
                elif hasattr(self.rs, "stop"):
                    self.rs.stop()
        except Exception:
            pass

    def _get_frames(self):
        """Trả (color_np, depth_frame hoặc None). Hỗ trợ rs wrapper có get_frames() hoặc read()."""
        if self.rs is None:
            return None, None
        if hasattr(self.rs, "get_frames"):
            return self.rs.get_frames()
        if hasattr(self.rs, "read"):
            return self.rs.read()
        raise RuntimeError("RealSense wrapper must implement get_frames() or read()")

    @staticmethod
    def _np_color(color, depth):
        """
        Chuẩn hóa về np.ndarray cho khung màu.
        - Nếu color đã là ndarray -> trả về
        - Nếu color là video_frame -> convert get_data()
        - Nếu color là depth_frame nhưng depth là video_frame -> swap
        """
        def is_depth(f): return hasattr(f, "get_distance")
        def is_video(f): return hasattr(f, "get_data") and not is_depth(f)

        if isinstance(color, np.ndarray):
            return color

        if is_video(color):
            try:
                import numpy as _np
                return _np.asanyarray(color.get_data())
            except Exception:
                return None

        if is_depth(color) and is_video(depth):
            try:
                import numpy as _np
                return _np.asanyarray(depth.get_data())
            except Exception:
                return None

        return None

    def _publish_action(self, action: str):
        """Publish một sự kiện IN/OUT ngay khi phát hiện."""
        mqtt_bus.publish_result({
            "type": "detect",
            "payload": {
                "method": "counter",
                "data": {"action": action}
            }
        }, qos=1)

    def _depth_ok(self, depth_frame, cx: int, cy: int) -> bool:
        if depth_frame is None or not hasattr(depth_frame, "get_distance"):
            return True  # không có depth thì bỏ qua filter
        try:
            dist = depth_frame.get_distance(int(cx), int(cy))
        except Exception:
            return True
        if dist <= 0:
            return False
        return (self.min_dist <= dist <= self.max_dist)

    def _loop(self):
        try:
            last_summary = time.time()
            while not self.stop_evt.is_set():
                color, depth = self._get_frames()
                color = self._np_color(color, depth)
                if color is None:
                    time.sleep(0.002)
                    continue

                h, w = color.shape[:2]
                line_x = int(w * self.line_x_ratio)

                # YOLO detect người (class=0)
                dets: List[Tuple[int, int, int, int]] = []
                try:
                    if hasattr(self.yolo, "detect_person"):
                        results = self.yolo.detect_person(color)
                    else:
                        # fallback: giả sử YOLO object có __call__
                        results = self.yolo(color, conf=0.35, verbose=False, classes=[0])
                except Exception:
                    results = None

                if results:
                    r = results[0] if len(results) > 0 else None
                    if r is not None and hasattr(r, "boxes"):
                        for b in r.boxes:
                            xyxy = b.xyxy[0].cpu().numpy().astype(int).tolist()
                            x1, y1, x2, y2 = xyxy
                            cx = int((x1 + x2) / 2)
                            cy = int((y1 + y2) / 2)
                            if self.use_depth and not self._depth_ok(depth, cx, cy):
                                continue
                            # bỏ bbox quá nhỏ để giảm nhiễu
                            if (x2 - x1) * (y2 - y1) < 8000:
                                continue
                            dets.append((x1, y1, x2, y2))

                tracks = self.tracker.update(dets)
                now = time.time()

                for tid, tr in tracks.items():
                    x1, y1, x2, y2 = tr.bbox
                    cx = int((x1 + x2) / 2)

                    prev_side = tr.side
                    cur_side = get_side(cx, line_x)
                    tr.side = cur_side

                    if prev_side != 'unknown' and cur_side != prev_side:
                        # crossing line
                        if is_inside(cur_side, self.camera_side) and not tr.counted_in:
                            self.total_in += 1
                            tr.counted_in, tr.counted_out = True, False
                            self.enter_times.append(now)
                            # Log & publish ngay
                            log.info("[VÀO] Track %d | IN=%d OUT=%d", tid, self.total_in, self.total_out)
                            print(f'in=1 | IN={self.total_in} OUT={self.total_out}', flush=True)
                            self._publish_action("IN")
                        elif not is_inside(cur_side, self.camera_side) and not tr.counted_out:
                            self.total_out += 1
                            tr.counted_out, tr.counted_in = True, False
                            log.info("[RA ] Track %d | IN=%d OUT=%d", tid, self.total_in, self.total_out)
                            print(f'out=1 | IN={self.total_in} OUT={self.total_out}', flush=True)
                            self._publish_action("OUT")

                # cảnh báo nhiều người cùng vào trong cửa sổ thời gian
                while self.enter_times and now - self.enter_times[0] > self.enter_window:
                    self.enter_times.popleft()
                if len(self.enter_times) >= 2 and (now - self.last_multi_log_ts) > self.enter_window:
                    log.info("[ALERT] Có %d người CÙNG đi VÀO!", len(self.enter_times))
                    self.last_multi_log_ts = now

                # log định kỳ tổng kết
                if (now - last_summary) >= float(self.log_interval):
                    log.info("SUMMARY (periodic): IN=%d OUT=%d", self.total_in, self.total_out)
                    last_summary = now

        finally:
            self._cleanup()
            self._release_camera_lock()
            log.info("Counter STOP (cleanup) | FINAL: IN=%d OUT=%d", self.total_in, self.total_out)
