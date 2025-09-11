from __future__ import annotations
import os, logging
from typing import Optional, Dict, Any, Tuple, List

import numpy as np
import cv2
from ultralytics import YOLO
from insightface.app import FaceAnalysis

log = logging.getLogger("vision.followme.engine")

# ---------- helpers ----------
def _median_distance(depth_frame, box: Tuple[int,int,int,int]) -> float:
    if depth_frame is None or not hasattr(depth_frame, "get_distance"):
        return 0.0
    x1,y1,x2,y2 = box
    cx, cy = (x1+x2)//2, (y1+y2)//2
    roi = max(2, min(x2-x1, y2-y1)//4)
    vals = []
    for dx in range(-roi, roi, 5):
        for dy in range(-roi, roi, 5):
            px, py = cx+dx, cy+dy
            try:
                d = depth_frame.get_distance(int(px), int(py))
            except Exception:
                d = 0.0
            if 0.25 < d < 6.0:
                vals.append(d)
    return float(np.median(vals)) if vals else 0.0

def _face_embed(face_app: FaceAnalysis, color_bgr: np.ndarray, person_box: Tuple[int,int,int,int]) -> Optional[np.ndarray]:
    x1,y1,x2,y2 = person_box
    box_h = max(1, y2-y1)
    y_top, y_mid = y1, y1 + int(box_h*0.5)
    roi = color_bgr[max(0,y_top):max(0,min(color_bgr.shape[0],y_mid)),
                    max(0,x1):max(0,min(color_bgr.shape[1],x2))]
    if roi.size == 0:
        return None
    faces = face_app.get(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
    if not faces:
        return None
    best = max(faces, key=lambda f: max(0,(f.bbox[2]-f.bbox[0]))*max(0,(f.bbox[3]-f.bbox[1])))
    return best.embedding

def _cosine_dist(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a)*np.linalg.norm(b)) + 1e-8
    return 1.0 - float(np.dot(a, b) / denom)

# ---------- optional gestures via MediaPipe (không bắt buộc) ----------
try:
    import mediapipe as mp
    _MP_OK = True
except Exception:
    mp = None
    _MP_OK = False
    log.warning("MediaPipe not available; gesture control disabled.")

def _count_fingers_mp(hand_landmarks) -> int:
    tip = [4,8,12,16,20]
    fingers = []
    # ngón cái: so sánh x
    fingers.append(1 if hand_landmarks.landmark[tip[0]].x < hand_landmarks.landmark[tip[0]-1].x else 0)
    # 4 ngón còn lại: so sánh y (tip cao hơn pip)
    for i in range(1,5):
        fingers.append(1 if hand_landmarks.landmark[tip[i]].y < hand_landmarks.landmark[tip[i]-2].y else 0)
    return sum(fingers)

class _GestureLatch:
    def __init__(self): self.curr=None; self.frames=0
    def step(self, name: Optional[str], need: int) -> bool:
        if not name:
            self.curr=None; self.frames=0; return False
        if name == self.curr: self.frames += 1
        else: self.curr, self.frames = name, 1
        return self.frames >= need

# ---------- Engine ----------
class FollowMeEngine:
    """
    step(color_bgr, depth_frame) -> List[dict]
    Events trả về:
      {"event":"registered"}   : đã lấy embedding chủ nhân
      {"event":"lost"}         : mất chủ nhân
      {"event":"reacquired"}   : khớp lại chủ nhân
      {"state":"following"}    : đang theo dõi (sau ✌️)
      {"state":"paused"}       : tạm dừng (sau 🖖)
    Quy tắc: chỉ khi identity_ok=True (đang là đúng người) mới xử lý cử chỉ.
    """

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        cfg = dict(config or {})
        self.yolo_weights = cfg.get("yolo_weights", os.getenv("YOLO_WEIGHTS","yolo11s.pt"))
        self.yolo_conf    = float(cfg.get("yolo_conf", 0.5))
        self.rec_range_m  = float(cfg.get("recognition_range_m", 2.5))
        self.face_thr     = float(cfg.get("face_distance_thr", 0.40))

        self.reg_need     = int(cfg.get("register_confirm_frames", 11))
        self.follow_need  = int(cfg.get("follow_confirm_frames", 10))
        self.pause_need   = int(cfg.get("pause_confirm_frames", 5))

        self.auto_resume_on_reacquire = bool(cfg.get("auto_resume_on_reacquire", False))

        # models
        self.yolo = YOLO(self.yolo_weights)
        self.face_app = FaceAnalysis(name="buffalo_s", allowed_modules=['detection','recognition'])
        # Jetson thường dùng CPU provider; PC x86 có thể dùng CUDA nếu onnxruntime-gpu sẵn sàng.
        try:
            self.face_app.prepare(ctx_id=-1, det_size=(640,640))
        except Exception:
            self.face_app.prepare(ctx_id=0, det_size=(640,640))
        if _MP_OK:
            self._mp_hands = mp.solutions.hands
            self.hands = self._mp_hands.Hands(max_num_hands=2, min_detection_confidence=0.5)
            log.info("MediaPipe Hands initialized")
        else:
            self.hands = None

        # state
        self.target_embedding: Optional[np.ndarray] = None
        self.identity_ok: bool = False     # chỉ True khi đang khớp chủ nhân
        self.following: bool = False       # chỉ True sau khi ✌️ while identity_ok
        self._lost_flag: bool = False

        # gesture latches
        self.reg_latch    = _GestureLatch()
        self.follow_latch = _GestureLatch()
        self.pause_latch  = _GestureLatch()

    # public status
    def status(self) -> Dict[str, Any]:
        return {
            "has_face_embedding": self.target_embedding is not None,
            "identity_ok": self.identity_ok,
            "following": self.following,
        }

    # helpers
    def _roi_fingers(self, color_bgr: np.ndarray, box: Tuple[int,int,int,int]) -> Optional[int]:
        if self.hands is None: return None
        x1,y1,x2,y2 = box
        h = max(1, y2-y1)
        y_top, y_40 = y1, y1 + int(h*0.4)
        roi = color_bgr[max(0,y_top):min(color_bgr.shape[0],y_40),
                        max(0,x1):min(color_bgr.shape[1],x2)]
        if roi.size == 0:
            return None
        rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        try:
            res = self.hands.process(rgb)
        except Exception:
            return None
        if not getattr(res, "multi_hand_landmarks", None):
            return None
        return _count_fingers_mp(res.multi_hand_landmarks[0])

    # main
    def step(self, color_bgr: np.ndarray, depth_frame) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []

        # 1) detect persons
        yolores = self.yolo.track(color_bgr, conf=self.yolo_conf, verbose=False, persist=True)
        persons: List[dict] = []
        for r in yolores:
            for box in getattr(r, "boxes", []):
                try:
                    if int(box.cls) != 0:  # 0 = person
                        continue
                except Exception:
                    continue
                x1,y1,x2,y2 = map(int, box.xyxy[0])
                if (x2-x1)*(y2-y1) < 10_000:
                    continue
                dist = _median_distance(depth_frame, (x1,y1,x2,y2))
                persons.append({"box": (x1,y1,x2,y2), "distance": dist})

        # chọn candidate gần nhất trong phạm vi
        candidate = None
        near = [p for p in persons if 0.3 < p["distance"] < self.rec_range_m] or persons
        near.sort(key=lambda p: p["distance"] if p["distance"]>0 else 9e9)
        candidate = near[0] if near else None

        # 2) Registration: cần ✌️ giữ N khung, rồi LẤY EMBEDDING
        if self.target_embedding is None:
            if candidate is not None and self.hands is not None:
                fingers = self._roi_fingers(color_bgr, candidate["box"])
                gesture = "register" if fingers == 1 else None
            else:
                gesture = None

            if self.reg_latch.step(gesture, self.reg_need) and candidate is not None:
                emb = _face_embed(self.face_app, color_bgr, candidate["box"])
                if emb is not None:
                    self.target_embedding = emb
                    self.identity_ok = True
                    self._lost_flag = False
                    self.following = False
                    events.append({"event":"registered"})
                    log.info("FOLLOW: registered owner (embedding ok)")
            return events  # chưa đăng ký xong thì dừng tại đây

        # 3) Sau đăng ký: kiểm tra IDENTITY bằng embedding
        matched = False
        if candidate is not None:
            emb = _face_embed(self.face_app, color_bgr, candidate["box"])
            if emb is not None:
                matched = (_cosine_dist(emb, self.target_embedding) < self.face_thr)

        if not matched:
            # không thấy người hoặc không khớp chủ nhân → LOST (1 lần)
            if not self._lost_flag:
                self._lost_flag = True
                if self.identity_ok or self.following:
                    log.info("FOLLOW: LOST owner")
                self.identity_ok = False
                self.following = False
                events.append({"event":"lost"})
            return events  # khi mất người: KHÔNG xử lý cử chỉ

        # matched == True
        if self._lost_flag:
            self._lost_flag = False
            self.identity_ok = True
            events.append({"event":"reacquired"})
            log.info("FOLLOW: RE-ACQUIRED owner")
            if self.auto_resume_on_reacquire:
                # tự tiếp tục following (tuỳ chọn)
                self.following = True
                events.append({"state":"following"})
        else:
            # vẫn đang khớp chủ nhân
            self.identity_ok = True

        # 4) Chỉ khi identity_ok=True mới xử lý cử chỉ
        if not self.identity_ok:
            return events

        fingers = self._roi_fingers(color_bgr, candidate["box"]) if self.hands is not None else None
        g_follow = "follow" if fingers == 2 else None
        g_pause  = "pause"  if fingers == 3 else None

        if self.follow_latch.step(g_follow, self.follow_need):
            if not self.following:
                self.following = True
                events.append({"state":"following"})
                log.info("FOLLOW: state=following")

        if self.pause_latch.step(g_pause, self.pause_need):
            if self.following:
                self.following = False
                events.append({"state":"paused"})
                log.info("FOLLOW: state=paused")

        return events
