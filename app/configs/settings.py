# app/configs/settings.py
from __future__ import annotations
from typing import Optional, Union
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="VISION_",
        extra="ignore",
    )

    TAG_RGB_DEVICE: int | str = 0          # hoặc "/dev/video0"
    TAG_RGB_WIDTH: int = 640
    TAG_RGB_HEIGHT: int = 480
    TAG_RGB_FPS: int = 30

    TAG_CALIB_FILE: str = "/app/models/camera_calib2.npz"  # chứa K, dist, img_size
    TAG_SIZE_M: float = 0.135
    TAG_FAMILY: str = "tag36h11"

    TAG_NTHREADS: int = 2
    TAG_QUAD_DECIMATE: float = 1.0
    TAG_QUAD_SIGMA: float = 0.0
    TAG_REFINE_EDGES: int = 1
    TAG_DECODE_SHARPENING: float = 0.25

    TAG_ALPHA_POS: float = 0.25
    TAG_ALPHA_DIST: float = 0.25
    TAG_ALPHA_ANGLE: float = 0.25

    # ---------- MQTT ----------
    MQTT_HOST: str = "127.0.0.1"
    MQTT_PORT: int = 1883
    MQTT_KEEPALIVE: int = 60
    MQTT_USERNAME: Optional[str] = None
    MQTT_PASSWORD: Optional[str] = None
    MQTT_CLIENT_ID: str = "vision-svc"
    MQTT_METHOD_TOPIC: str = "vetc/robot/vision/method"
    MQTT_RESULT_TOPIC: str = "vetc/robot/vision/result"

    # ---------- RGB Camera (2D) - defaults dùng chung (counter sẽ dùng cái này) ----------
    RGB_CAM_DEVICE: Union[int, str] = 0
    RGB_CAM_WIDTH: int = 640
    RGB_CAM_HEIGHT: int = 480
    RGB_CAM_FPS: int = 30
    RGB_USE_MJPEG: bool = True         # <— bật MJPG nếu cam hỗ trợ
    RGB_BUFFERSIZE: int = 2 

    # ---------- RealSense (3D) ----------
    RS_WIDTH: int = 640
    RS_HEIGHT: int = 480
    RS_FPS: int = 30

    # ---------- Counter defaults ----------
    COUNTER_YOLO_WEIGHTS: str = "yolo11s.pt"
    COUNTER_CAMERA_SIDE: str = "left"
    COUNTER_LINE_X: float = 0.5
    COUNTER_CONF: float = 0.35
    COUNTER_DEVICE: str = "auto"
    COUNTER_ENTER_WINDOW: float = 1.0
    COUNTER_LOG_INTERVAL: float = 2.0
    COUNTER_MIN_DIST: float = 0.2
    COUNTER_MAX_DIST: float = 6.0

    # ---------- Unphysics defaults (riêng, không ảnh hưởng counter) ----------
    # -> để bạn không phải gửi overrides
    UNPHYSICS_RGB_DEVICE: Union[int, str] = "/dev/video0"
    UNPHYSICS_RGB_WIDTH: int = 640
    UNPHYSICS_RGB_HEIGHT: int = 480
    UNPHYSICS_RGB_FPS: int = 30
    UNPHYSICS_COOLDOWN_MS: float = 500.0
    UNPHYSICS_ARM_FRAMES: int = 6
    UNPHYSICS_PAUSE_FRAMES: int = 6
    UNPHYSICS_STOP_IGNORE_S: float = 1.5
    # mới: xử lý Mediapipe ở kích thước nhỏ và frame-skip
    UNPHYSICS_PROC_WIDTH: int = 320     # <— ảnh downscale cho Mediapipe
    UNPHYSICS_PROC_HEIGHT: int = 240
    UNPHYSICS_FRAME_SKIP: int = 1         # bỏ qua pause vài giây đầu

    # ---------- Follow-me defaults ----------
    FOLLOW_COOLDOWN_MS: float = 350.0

settings = Settings()
