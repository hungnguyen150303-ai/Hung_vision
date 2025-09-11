# app/plugins/unphysics_engine.py
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger("vision.unphysics.engine")

# MediaPipe Hands
try:
    import mediapipe as mp
    _MP_OK = True
except Exception:
    mp = None
    _MP_OK = False
    log.warning("Không tìm thấy MediaPipe. UnphysicsEngine sẽ không phát hiện ngón tay.")


@dataclass
class _SimpleTimer:
    t0: Optional[float] = None
    def start(self, now: float): self.t0 = now
    def reset(self): self.t0 = None
    def elapsed_ms(self, now: float) -> float:
        return 1e12 if self.t0 is None else (now - self.t0) * 1000.0
    def valid(self) -> bool: return self.t0 is not None


@dataclass
class _GestureState:
    center: Optional[Tuple[int, int]] = None
    tip: Optional[Tuple[int, int]] = None
    prev_tip: Optional[Tuple[int, int]] = None


class UnphysicsEngine:
    """
    Chuẩn theo unphysics.py:
      - Chỉ theo dõi ngón giữa (landmark 12)
      - 2 ngón (bỏ ngón cái) -> ARMED, 3 ngón -> PAUSED
      - Đặt CENTER khi tip đứng yên ≥150ms; kéo vượt 70px -> phát lệnh 1 lần
      - Cooldown cố định 1100ms giữa 2 lệnh
    Trả về events dạng:
      - {"state": "armed"|"paused"}
      - {"action": "LEFT"|"RIGHT"|"UP"|"DOWN"}
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = dict(config or {})

        # THAM SỐ CỐ ĐỊNH (theo file gốc)
        self.center_radius: int = int(cfg.get("center_radius", 40))
        self.pull_threshold: float = float(cfg.get("pull_threshold", 70.0))
        self.stop_frames_threshold: int = int(cfg.get("stop_frames_threshold", 12))
        self.active_frames_threshold: int = int(cfg.get("active_frames_threshold", 6))
        self.gesture_cooldown_ms: float = float(cfg.get("gesture_cooldown_ms", 1100.0))
        self.tip_stationary_threshold: float = float(cfg.get("tip_stationary_threshold", 15.0))
        self.tip_stationary_duration_ms: float = float(cfg.get("tip_stationary_duration_ms", 150.0))

        # Trạng thái
        self.state = _GestureState()
        self.active_mode: bool = False
        self.ready_for_new_gesture: bool = False
        self.stop_counter: int = 0
        self.active_counter: int = 0
        self.cooldown_timer = _SimpleTimer()
        self.center_timer = _SimpleTimer()
        self.last_command: Optional[str] = None

        if _MP_OK:
            self._mp_hands = mp.solutions.hands
            self._hands = self._mp_hands.Hands(
                max_num_hands=1,
                min_detection_confidence=0.80,
                min_tracking_confidence=0.80
            )
            log.info("MediaPipe Hands ready")
        else:
            self._mp_hands = None
            self._hands = None

    # ---------- helpers ----------
    @staticmethod
    def _count_fingers(states: Dict[str, bool], ignore_thumb: bool = True) -> int:
        keys = ["index", "middle", "ring", "pinky"] if ignore_thumb else ["thumb", "index", "middle", "ring", "pinky"]
        return sum(1 for k in keys if states.get(k, False))

    @staticmethod
    def _is_extended_y(tip, pip) -> bool:
        return tip.y < pip.y  # tip cao hơn (ảnh toạ độ y xuống dưới)

    @staticmethod
    def _thumb_extended(tip, ip, is_right: bool) -> bool:
        # ảnh đã flip bởi camera trước? engine không flip nữa, giả sử camera chuẩn.
        # nếu khung hình mirror thì logic trái/phải có thể cần đảo.
        return (tip.x > ip.x) if is_right else (tip.x < ip.x)

    def _finger_states(self, hl, hand_label: str) -> Dict[str, bool]:
        is_right = (hand_label.lower() == "right")
        tip = hl.landmark
        return {
            "thumb":  self._thumb_extended(tip[4], tip[3], is_right),
            "index":  self._is_extended_y(tip[8],  tip[6]),
            "middle": self._is_extended_y(tip[12], tip[10]),
            "ring":   self._is_extended_y(tip[16], tip[14]),
            "pinky":  self._is_extended_y(tip[20], tip[18]),
        }

    @staticmethod
    def _direction(center_xy: Tuple[int, int], tip_xy: Tuple[int, int]) -> str:
        # Map hướng giống file gốc:
        dx = tip_xy[0] - center_xy[0]
        dy = center_xy[1] - tip_xy[1]
        ang = math.degrees(math.atan2(dy, dx))
        if -45 <= ang < 45:    return "RIGHT"
        if 45 <= ang < 135:    return "UP"
        if -135 <= ang < -45:  return "DOWN"
        return "LEFT"

    # ---------- public ----------
    def status(self) -> Dict[str, Any]:
        return {
            "armed": self.active_mode,
            "center_radius": self.center_radius,
            "pull_threshold": self.pull_threshold,
            "cooldown_ms": self.gesture_cooldown_ms,
        }

    def step(self, color_bgr: Optional[np.ndarray], depth_frame=None) -> List[Dict[str, Any]]:
        """
        Xử lý 1 frame. Trả về list events: [{"state":...}|{"action":...}, ...]
        """
        out: List[Dict[str, Any]] = []
        if color_bgr is None or not isinstance(color_bgr, np.ndarray):
            self.state.prev_tip = None
            self.center_timer.reset()
            return out
        if not _MP_OK or self._hands is None:
            return out

        h, w = color_bgr.shape[:2]
        rgb = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)
        res = self._hands.process(rgb)

        now = cv2.getTickCount() / cv2.getTickFrequency()  # giây, độ chính xác cao

        self.state.tip = None
        command: Optional[str] = None

        if res.multi_hand_landmarks:
            hl = res.multi_hand_landmarks[0]
            hand_label = "right"
            if res.multi_handedness and len(res.multi_handedness) > 0:
                hand_label = res.multi_handedness[0].classification[0].label  # "Left"/"Right"

            # ---- Trạng thái ngón & đếm (bỏ ngón cái) ----
            states = self._finger_states(hl, hand_label)
            ext = self._count_fingers(states, ignore_thumb=True)  # chỉ index/middle/ring/pinky

            # ---- CHỈ BÁM NGÓN GIỮA ----
            if states.get("middle", False):
                mid_tip = hl.landmark[12]
                tip_xy = (int(mid_tip.x * w), int(mid_tip.y * h))
                self.state.tip = tip_xy

                # phát hiện tip đứng yên -> đặt center
                if self.state.prev_tip is not None and tip_xy is not None:
                    dx = abs(tip_xy[0] - self.state.prev_tip[0])
                    dy = abs(tip_xy[1] - self.state.prev_tip[1])
                    if dx < self.tip_stationary_threshold and dy < self.tip_stationary_threshold:
                        if not self.center_timer.valid():
                            self.center_timer.start(now)
                        elif self.center_timer.elapsed_ms(now) >= self.tip_stationary_duration_ms:
                            self.state.center = (tip_xy[0], tip_xy[1])
                            self.ready_for_new_gesture = True
                            self.center_timer.reset()
                    else:
                        self.center_timer.reset()
                self.state.prev_tip = tip_xy
            else:
                # Không duỗi ngón giữa -> không điều khiển, reset timer đặt center
                self.state.prev_tip = None
                self.center_timer.reset()

            # ---- KÍCH HOẠT / TẠM DỪNG ----
            if ext == 2:
                self.active_counter += 1
                self.stop_counter = 0
                if self.active_counter >= self.active_frames_threshold and not self.active_mode:
                    self.active_mode = True
                    out.append({"state": "armed"})
                    log.info("UNPHYSICS ARMED (✌️)")
            elif ext == 3:
                self.stop_counter += 1
                self.active_counter = 0
                if self.stop_counter >= self.stop_frames_threshold and self.active_mode:
                    self.active_mode = False
                    self.ready_for_new_gesture = False
                    out.append({"state": "paused"})
                    log.info("UNPHYSICS PAUSED (3 ngón)")
            else:
                self.active_counter = 0
                self.stop_counter = 0

            # ---- RA LỆNH 1 LẦN ----
            if self.active_mode and self.state.center and self.state.tip and self.ready_for_new_gesture:
                dist = math.hypot(self.state.tip[0] - self.state.center[0],
                                  self.state.tip[1] - self.state.center[1])
                if dist > self.pull_threshold:
                    # cooldown nội tại (1100ms)
                    if (not self.cooldown_timer.valid()) or (self.cooldown_timer.elapsed_ms(now) >= self.gesture_cooldown_ms):
                        self.cooldown_timer.start(now)
                        command = self._direction(self.state.center, self.state.tip)
                        self.ready_for_new_gesture = False
                        self.last_command = command
                        out.append({"action": command})
        else:
            # mất tay -> reset
            self.active_mode = False
            self.ready_for_new_gesture = False
            self.state.prev_tip = None
            self.center_timer.reset()
            self.active_counter = 0
            self.stop_counter = 0

        return out
