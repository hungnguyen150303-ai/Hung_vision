# app/core/container.py
from __future__ import annotations
import threading

class _Container:
    def __init__(self):
        # 2 lock tách biệt
        self.camera_lock_rgb = threading.RLock()
        self.camera_lock_rs  = threading.RLock()

        from app.services.counter_service import CounterService
        self.counter = CounterService()
        self.counter.set_camera_lock(self.camera_lock_rgb)   # <— dùng lock RGB

        from app.services.unphysics_service import UnphysicsService
        self.unphysics = UnphysicsService()
        self.unphysics.set_camera_lock(self.camera_lock_rgb) # <— dùng lock RGB

        from app.services.followme_service import FollowMeService
        self.followme = FollowMeService()
        self.followme.set_camera_lock(self.camera_lock_rs)   # <— dùng lock RS

container = _Container()
