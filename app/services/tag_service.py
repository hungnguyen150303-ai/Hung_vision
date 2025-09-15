# app/services/tag_service.py
from __future__ import annotations
import logging, threading, time
from typing import Optional, Dict, Any, Tuple, List
import numpy as np

from app.mqtt.client import mqtt_bus

log = logging.getLogger("vision.tag")

class TagService:
    """
    Service 'tagdata' — phát hiện AprilTag và publish pose.
    Publish:
      - state: boot | tag_found | tag_lost | stop | device_error
      - detect: {id, family, x, y, angle, distance}
    """
    def __init__(self) -> None:
        self._lock: Optional[threading.RLock] = None
        self._t: Optional[threading.Thread] = None
        self._running: bool = False
        self.rs = None       # camera wrapper (OpenCVCamera / RealSenseCamera)
        self.engine = None   # TagEngine

    def set_camera_lock(self, lock: threading.RLock): self._lock = lock
    def is_running(self) -> bool: return bool(self._running)

    def status(self) -> Dict[str, Any]:
        st = {"running": self._running}
        try:
            if hasattr(self.engine, "cfg"):
                st["config"] = {
                    "family": self.engine.cfg.family,
                    "tag_size_m": self.engine.cfg.tag_size_m,
                    "calib_file": self.engine.cfg.calib_file,
                }
        except Exception: pass
        return st

    # --- MQTT publish helpers ---
    def _pub_state(self, state: str) -> None:
        mqtt_bus.publish_result({"type":"state","payload":{"method":"tagdata","data":{"state": state}}}, qos=1, retain=False)

    def _pub_detect(self, data: Dict[str, Any]) -> None:
        mqtt_bus.publish_result({"type":"detect","payload":{"method":"tagdata","data": data}}, qos=1, retain=False)

    # --- camera I/O ---
    def _read(self) -> Tuple[Optional[np.ndarray], Optional[object]]:
        if self.rs is None: return None, None
        fn = getattr(self.rs, "get_frames", None)
        if callable(fn): return self.rs.get_frames()
        fn = getattr(self.rs, "read", None)
        if callable(fn): return self.rs.read()
        return None, None

    def _probe_and_log(self) -> bool:
        kind = getattr(self.rs, "kind", "unknown")
        chk = getattr(self.rs, "check_connectivity", None)
        if callable(chk):
            ok, msg = chk(timeout_s=1.5)
            if ok:
                log.info("ĐÃ KẾT NỐI camera %s: %s", kind, msg)
                return True
            log.error("Chưa kết nối thiết bị (%s): %s", kind, msg)
            return False
        # fallback 1 frame
        t0 = time.time()
        while time.time() - t0 < 1.5:
            color, depth = self._read()
            if color is not None:
                h, w = color.shape[:2]
                txt = "3D" if (kind == "3D" or depth is not None) else "2D"
                log.info("ĐÃ KẾT NỐI camera %s (fallback) %dx%d", txt, w, h)
                return True
            time.sleep(0.05)
        log.error("Chưa kết nối thiết bị (không nhận được frame)")
        return False

    # --- main loop ---
    def _loop(self) -> None:
        log.info("TagService START (AprilTag).")
        self._pub_state("boot")
        try:
            while self._running:
                color, _ = self._read()
                if color is None:
                    time.sleep(0.01)
                    continue
                try:
                    events = self.engine.step(color)
                except Exception as e:
                    log.exception("TagEngine step error: %s", e)
                    events = []

                for ev in events:
                    if "state" in ev:
                        st = ev["state"]
                        log.info("tag state=%s", st)
                        self._pub_state(st)
                    if "detect" in ev:
                        self._pub_detect(ev["detect"])
        finally:
            log.info("TagService STOP")
            self._pub_state("stop")

    # --- API ---
    def start(self, *, rs, engine) -> None:
        if self._running: return
        self.rs, self.engine = rs, engine
        try:
            op = getattr(self.rs, "open", None)
            if callable(op): op()
        except Exception as e:
            log.warning("camera open error: %s", e)

        if not self._probe_and_log():
            self._pub_state("device_error")
            self.rs = None
            return

        self._running = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self) -> None:
        if not self._running:
            # đóng camera nếu còn mở
            try:
                cl = getattr(self.rs, "close", None)
                if callable(cl): cl()
            except Exception: pass
            self.rs = None
            return

        self._running = False
        try:
            if self._t and self._t.is_alive():
                self._t.join(timeout=2.0)
        except Exception: pass
        self._t = None

        try:
            cl = getattr(self.rs, "close", None)
            if callable(cl): cl()
        except Exception: pass
        self.rs = None
