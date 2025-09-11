# app/services/followme_service.py
from __future__ import annotations
import logging, threading, time
from typing import Optional, Dict, Any, Tuple, List
import numpy as np
from app.mqtt.client import mqtt_bus

log = logging.getLogger("vision.followme")

class FollowMeService:
    """
    FOLLOW-ME service:
      - Đăng ký: giơ 1 ngón liên tục (engine phát 'registered')
      - Điều khiển: ✌️ 2 ngón -> FOLLOW; 🖖 3 ngón -> PAUSE
      - Mất dấu / nhận lại: 'lost' / 'reacquired'
      - Publish JSON lên vision/result mỗi khi có sự kiện
    """

    def __init__(self) -> None:
        self.thread: Optional[threading.Thread] = None
        self.stop_evt = threading.Event()
        self.rs = None           # wrapper có get_frames() -> (color(np.ndarray|frame), depth_frame)
        self.engine = None       # engine có step(color, depth) -> List[dict] các events
        self.running = False
        self.cfg: Dict[str, Any] = {}
        # camera lock
        self._cam_lock = None
        self._lock_acquired = False

    # ---- DI callbacks ----
    def set_camera_lock(self, lock):
        self._cam_lock = lock

    # ---- Public API ----
    def is_running(self) -> bool:
        return bool(self.running)

    def start(self, rs, engine, **cfg) -> None:
        if self.running:
            log.info("FollowMe already running.")
            return

        # acquire camera lock
        if self._cam_lock and not self._cam_lock.acquire(blocking=False):
            log.warning("Camera is busy by another service.")
            return
        self._lock_acquired = True

        try:
            self.rs = rs
            self.engine = engine
            self.cfg = dict(cfg)
            self.stop_evt.clear()
            self.thread = threading.Thread(target=self._loop, name="followme-loop", daemon=True)
            self.thread.start()
            self.running = True
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
            log.info("FollowMe STOP")

    def status(self) -> Dict[str, Any]:
        e = getattr(self.engine, "status", None)
        est = e() if callable(e) else {}
        return {"running": self.running, "config": dict(self.cfg), **(est or {})}

    # ---- internals ----
    def _release_camera_lock(self):
        if self._cam_lock and self._lock_acquired:
            try:
                self._cam_lock.release()
            except RuntimeError:
                pass
            self._lock_acquired = False
            time.sleep(0.2)  # grace để driver nhả hẳn

    def _cleanup(self):
        try:
            if self.rs is not None:
                if hasattr(self.rs, "close"): self.rs.close()
                elif hasattr(self.rs, "stop"): self.rs.stop()
        except Exception:
            pass

    def _get_frames(self) -> Tuple[Optional[np.ndarray], Optional[object]]:
        if self.rs is None:
            return None, None
        if hasattr(self.rs, "get_frames"):
            return self.rs.get_frames()
        if hasattr(self.rs, "read"):
            return self.rs.read()
        raise RuntimeError("RealSense wrapper must implement get_frames() or read()")

    @staticmethod
    def _np_color(color, depth):
        # đổi color video_frame -> np.ndarray; nếu bị đảo với depth thì lấy từ depth
        def is_depth(f): return hasattr(f, "get_distance")
        def is_video(f): return hasattr(f, "get_data") and not is_depth(f)
        if isinstance(color, np.ndarray): return color
        if is_video(color):
            import numpy as _np
            try: return _np.asanyarray(color.get_data())
            except Exception: return None
        if is_depth(color) and is_video(depth):
            import numpy as _np
            try: return _np.asanyarray(depth.get_data())
            except Exception: return None
        return None

    def _publish(self, data: Dict[str, Any]):
        # data là phần 'data' trong payload
        mqtt_bus.publish_result({
            "type": "detect",
            "payload": {
                "method": "follow_me",
                "data": data
            }
        }, qos=1)

    def _loop(self):
        log.info("FollowMe START | cfg=%s", self.cfg)
        print("FOLLOW-ME: Đưa 1 NGÓN để đăng ký | ✌️ 2 ngón để FOLLOW | 🖖 3 ngón để PAUSE", flush=True)
        try:
            while not self.stop_evt.is_set():
                color, depth = self._get_frames()
                color = self._np_color(color, depth)
                if color is None:
                    time.sleep(0.002)
                    continue

                try:
                    events: List[Dict[str, Any]] = self.engine.step(color, depth)
                except Exception:
                    events = []

                for ev in events:
                    # ev ví dụ: {"event":"registered"} | {"state":"following"} | {"event":"lost"} ...
                    if not isinstance(ev, dict): 
                        continue
                    # log ngắn gọn
                    if "state" in ev:
                        log.info("state=%s", ev["state"])
                        print(f"state={ev['state']}", flush=True)
                    elif "event" in ev:
                        log.info("event=%s", ev["event"])
                        print(f"event={ev['event']}", flush=True)
                    # publish
                    self._publish(ev)

        finally:
            self._cleanup()
            self._release_camera_lock()
            log.info("FollowMe STOP (cleanup)")
