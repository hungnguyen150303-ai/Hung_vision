# app/services/unphysics_service.py
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Dict, Any, Tuple

import numpy as np
from app.mqtt.client import mqtt_bus

log = logging.getLogger("vision.unphysics")


class UnphysicsService:
    """
    Service dùng engine UnphysicsEngine (chuẩn unphysics.py).
    - Không throttle thêm trong service (cooldown đã nằm trong engine = 1100ms)
    - Publish state/action lên vision/result
    """

    def __init__(self) -> None:
        self._cam_lock: Optional[threading.RLock] = None
        self._t: Optional[threading.Thread] = None
        self._running: bool = False

        self.rs = None        # camera wrapper: .read() or .get_frames()
        self.engine = None    # UnphysicsEngine

    # ---- lifecycle ----
    def set_camera_lock(self, lock: threading.RLock):
        self._cam_lock = lock

    def is_running(self) -> bool:
        return bool(self._running)

    def status(self) -> Dict[str, Any]:
        st = {"running": self._running}
        try:
            if hasattr(self.engine, "status"):
                st["engine"] = self.engine.status()
        except Exception:
            pass
        return st

    # ---- publish helpers ----
    def _publish(self, obj: Dict[str, Any]) -> None:
        try:
            mqtt_bus.publish_result(obj, qos=1, retain=False)
        except Exception as e:
            log.warning("Publish result failed: %s", e)

    def _emit_state(self, state: str) -> None:
        self._publish({
            "type": "state",
            "payload": {
                "method": "control_unphysics",
                "data": {"state": state}
            }
        })

    def _emit_action(self, action: str) -> None:
        self._publish({
            "type": "detect",
            "payload": {
                "method": "control_unphysics",
                "data": {"action": action}
            }
        })
        log.info("UNPHYSICS action=%s", action)

    # ---- I/O ----
    def _read_frame(self) -> Tuple[Optional[np.ndarray], Optional[object]]:
        if self.rs is None:
            return None, None
        fn = getattr(self.rs, "get_frames", None)
        if callable(fn):
            return self.rs.get_frames()
        fn = getattr(self.rs, "read", None)
        if callable(fn):
            return self.rs.read()
        return None, None

    # ---- loop ----
    def _loop(self) -> None:
        log.info("Unphysics START (RGB). CHỈ bám NGÓN GIỮA | Giữ tip đứng yên để đặt CENTER; kéo ra để ra lệnh | 2 ngón=ACTIVE, 3 ngón=STOP.")
        self._emit_state("boot")

        try:
            while self._running:
                color, depth = self._read_frame()
                if color is None:
                    time.sleep(0.002)
                    continue
                try:
                    events = self.engine.step(color, depth)
                except Exception as e:
                    log.exception("Engine step failed: %s", e)
                    events = []

                for ev in events:
                    if "state" in ev:
                        s = ev["state"]
                        log.info("ARMED (✌️)" if s == "armed" else "PAUSED (3 ngón)")
                        self._emit_state(s)
                    elif "action" in ev:
                        self._emit_action(str(ev["action"]).upper())
        finally:
            log.info("Unphysics STOP (cleanup)")
            self._emit_state("stop")

    # ---- API ----
    def start(self, *, rs, engine) -> None:
        if self._running:
            return
        self.rs = rs
        self.engine = engine

        # mở camera nếu có
        try:
            op = getattr(self.rs, "open", None)
            if callable(op):
                op()
        except Exception as e:
            log.warning("Camera open error: %s", e)

        self._running = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            if self._t and self._t.is_alive():
                self._t.join(timeout=2.0)
        except Exception:
            pass
        self._t = None

        # đóng camera nếu có
        try:
            cl = getattr(self.rs, "close", None)
            if callable(cl):
                cl()
        except Exception:
            pass
        self.rs = None
