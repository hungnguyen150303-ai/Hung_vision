# app/core/container.py
from __future__ import annotations
import threading

class _Container:
    def __init__(self):
        # Hai lock tách biệt cho camera 2D (RGB) và 3D (RealSense)
        self.camera_lock_rgb = threading.RLock()
        self.camera_lock_rs  = threading.RLock()

        # --- Counter (RGB) ---
        from app.services.counter_service import CounterService
        self.counter = CounterService()
        self.counter.set_camera_lock(self.camera_lock_rgb)

        # --- Control Unphysics (RGB) ---
        from app.services.unphysics_service import UnphysicsService
        self.unphysics = UnphysicsService()
        self.unphysics.set_camera_lock(self.camera_lock_rgb)

        # --- TagData (AprilTag, RGB) ---
        from app.services.tag_service import TagService
        self.tag = TagService()
        self.tag.set_camera_lock(self.camera_lock_rgb)

        # --- Follow Me (RealSense 3D) ---
        from app.services.followme_service import FollowMeService
        self.followme = FollowMeService()
        self.followme.set_camera_lock(self.camera_lock_rs)

        

container = _Container()
