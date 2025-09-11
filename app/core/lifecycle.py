# app/core/lifecycle.py
from __future__ import annotations

import logging
import time
from typing import Dict, Any, Optional, Callable

from fastapi import FastAPI

from app.configs.settings import settings
from app.core.container import container
from app.usecases.counter_usecases import (
    start_counter_uc, stop_counter_uc, status_uc as status_counter_uc
)
from app.usecases.unphysics_usecases import (
    start_unphysics_uc, stop_unphysics_uc, status_unphysics_uc
)
from app.usecases.followme_usecases import (
    start_followme_uc, stop_followme_uc, status_followme_uc
)

log = logging.getLogger("vision.lifecycle")


def register_lifecycle(app: FastAPI):

    # ---- ánh xạ method -> loại lock (camera) ----
    # rgb: dùng V4L2/OpenCV; rs: dùng RealSense
    METHOD_LOCK_KIND = {
        "counter": "rgb",
        "control_unphysics": "rgb",
        "follow_me": "rs",
    }

    def _get_lock_by_kind(kind: str):
        if kind == "rgb":
            return getattr(container, "camera_lock_rgb", None)
        if kind == "rs":
            return getattr(container, "camera_lock_rs", None)
        return None

    def _service_lock(svc) -> object:
        # các service đã có set_camera_lock(self, lock) -> self._cam_lock
        return getattr(svc, "_cam_lock", None)

    def _is_running(method: str) -> bool:
        if method == "counter":
            return container.counter.is_running()
        if method == "control_unphysics":
            return container.unphysics.is_running()
        if method == "follow_me":
            return container.followme.is_running()
        return False

    def _stop_service(method: str):
        try:
            if method == "counter":
                if container.counter.is_running(): stop_counter_uc(container.counter)
            elif method == "control_unphysics":
                if container.unphysics.is_running(): stop_unphysics_uc(container.unphysics)
            elif method == "follow_me":
                if container.followme.is_running(): stop_followme_uc(container.followme)
        except Exception as e:
            log.warning("Stop %s error: %s", method, e)

    def _stop_conflicts(target_method: str):
        """
        Dừng những service đang chạy mà dùng CÙNG lock loại camera với target_method.
        Khác lock thì giữ nguyên (cho phép chạy song song).
        """
        kind = METHOD_LOCK_KIND.get(target_method, None)
        target_lock = _get_lock_by_kind(kind) if kind else None
        if target_lock is None:
            # fallback: nếu không xác định được thì dừng tất cả
            _stop_all()
            return

        pairs = [
            ("counter", container.counter),
            ("control_unphysics", container.unphysics),
            ("follow_me", container.followme),
        ]
        for m, svc in pairs:
            if m == target_method:
                continue
            try:
                if getattr(svc, "is_running", lambda: False)():
                    if _service_lock(svc) is target_lock:
                        _stop_service(m)
                        log.info("Preempt: stop %s (same camera '%s')", m, kind)
            except Exception as e:
                log.warning("Preempt stop %s failed: %s", m, e)

    def _stop_all():
        for m in ("counter", "control_unphysics", "follow_me"):
            _stop_service(m)

    # --------- helpers về chờ lock ---------
    def _wait_lock(lock, timeout: float = 5.0, step: float = 0.05) -> bool:
        """Poll xem lock có rảnh không (acquire+release thử)."""
        if lock is None:
            return True
        end = time.time() + timeout
        while time.time() < end:
            if lock.acquire(blocking=False):
                lock.release()
                return True
            time.sleep(step)
        return False

    def _preempt_then_start(start_callable: Callable[[], Dict[str, Any]], target_method: str) -> Dict[str, Any]:
        """
        Dừng các service xung đột theo LOẠI CAMERA -> chờ lock phù hợp -> start (retry ngắn nếu camera nhả chậm).
        - Nếu target đang chạy sẵn: trả status ngay (idempotent).
        """
        if _is_running(target_method):
            log.info("Start %s ignored: already running", target_method)
            # trả snapshot nhỏ của riêng service
            if target_method == "counter":
                return status_counter_uc(container.counter)
            if target_method == "control_unphysics":
                return status_unphysics_uc(container.unphysics)
            if target_method == "follow_me":
                return status_followme_uc(container.followme)
            return {"ok": True, "running": True}

        # dừng xung đột theo loại camera
        _stop_all()

        # chờ đúng loại lock
        kind = METHOD_LOCK_KIND.get(target_method, None)
        lock = _get_lock_by_kind(kind) if kind else None
        _wait_lock(lock, timeout=5.0)

        time.sleep(0.2)  # grace nhỏ
        last_res: Dict[str, Any] = {}
        for _ in range(5):
            res = start_callable()
            last_res = res if isinstance(res, dict) else {}
            if last_res.get("running"):
                return last_res
            time.sleep(0.3)
        return last_res

    # --------- MQTT dispatcher ---------
    @app.on_event("startup")
    def on_startup():
        from app.mqtt.client import mqtt_bus

        def _snapshot():
            return {
                "running": any([
                    container.counter.is_running(),
                    container.unphysics.is_running(),
                    container.followme.is_running()
                ]),
                "counter": status_counter_uc(container.counter),
                "unphysics": status_unphysics_uc(container.unphysics),
                "follow_me": status_followme_uc(container.followme),
                "current_method":
                    "counter" if container.counter.is_running() else
                    ("control_unphysics" if container.unphysics.is_running() else
                     ("follow_me" if container.followme.is_running() else "idle"))
            }

        def _dispatch(mtype: str, method: str, overrides: Optional[Dict[str, Any]]):
            """
            Nhận JSON trên topic vision/method:
              { "type": "start|stop|set", "payload": { "method": "counter|control_unphysics|follow_me", "overrides": {...} } }
            """
            m = (method or "").lower()
            t = (mtype or "").lower()
            o = overrides or {}

            if m == "counter":
                if t == "start":
                    return _preempt_then_start(
                        lambda: start_counter_uc(container.counter, settings=settings, overrides=o),
                        "counter"
                    )
                elif t == "stop":
                    return stop_counter_uc(container.counter)
                elif t == "set":
                    return status_counter_uc(container.counter)

            elif m == "control_unphysics":
                if t == "start":
                    return _preempt_then_start(
                        lambda: start_unphysics_uc(container.unphysics, settings=settings, overrides=o),
                        "control_unphysics"
                    )
                elif t == "stop":
                    return stop_unphysics_uc(container.unphysics)
                elif t == "set":
                    return status_unphysics_uc(container.unphysics)

            elif m == "follow_me":
                if t == "start":
                    return _preempt_then_start(
                        lambda: start_followme_uc(container.followme, settings=settings, overrides=o),
                        "follow_me"
                    )
                elif t == "stop":
                    return stop_followme_uc(container.followme)
                elif t == "set":
                    return status_followme_uc(container.followme)

            # default: trả snapshot toàn hệ
            return _snapshot()

        mqtt_bus.start(
            settings,
            on_method=_dispatch,
            get_status=_snapshot,
        )
        log.info("Lifecycle ready (vision/method)")

    @app.on_event("shutdown")
    def on_shutdown():
        _stop_all()
        try:
            from app.mqtt.client import mqtt_bus
            mqtt_bus.stop()
        except Exception:
            pass
