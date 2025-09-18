# Jetson / L4T r36.4.0 (JetPack 6.1)
FROM dustynv/l4t-pytorch:r36.4.0

# ==== build args / env để giảm RAM ====
ARG MAKE_JOBS=1
ARG WITH_FOLLOWME_EXTRAS=0   # 0 = không cài insightface khi build
ENV MAKEFLAGS=-j${MAKE_JOBS} \
    CMAKE_BUILD_PARALLEL_LEVEL=${MAKE_JOBS} \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_DEFAULT_TIMEOUT=180 \
    GLOG_minloglevel=2 \
    TF_CPP_MIN_LOG_LEVEL=2 \
    # ép pip ưu tiên binary để né build từ source
    PIP_PREFER_BINARY=1

# 1) Gói hệ thống — chỉ những gì cần thiết, ưu tiên APT (không compile)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config \
    libssl-dev libusb-1.0-0-dev libudev-dev \
    libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev \
    libeigen3-dev \
    udev v4l-utils ffmpeg curl ca-certificates \
    python3-opencv python3-pip \
    python3-numpy python3-scipy python3-sklearn python3-sklearn-lib \
    python3-sympy python3-networkx python3-matplotlib python3-imageio \
 && rm -rf /var/lib/apt/lists/*

# 2) librealsense từ APT (né compile)
RUN set -e; \
    apt-get update && apt-get install -y --no-install-recommends gnupg software-properties-common && \
    curl -sS https://librealsense.intel.com/Debian/IntelRealSenseLFS.key | apt-key add - && \
    add-apt-repository "deb https://librealsense.intel.com/Debian/apt-repo jammy main" && \
    apt-get update && apt-get install -y --no-install-recommends \
      librealsense2 librealsense2-utils librealsense2-gl python3-realsense2 \
    && rm -rf /var/lib/apt/lists/*

# 3) AprilTag từ APT (né compile)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libapriltag3 python3-apriltag \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt

# 4) Python deps (nhẹ, né build from source)
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir -r /app/requirements.txt --no-deps \
 && python3 -m pip install --no-cache-dir "ultralytics>=8.2.0,<9" --no-deps \
 && python3 -m pip install --no-cache-dir fastapi "uvicorn[standard]" paho-mqtt

# (TÙY CHỌN) Mediapipe — nếu bạn thực sự dùng trong unphysics. Có wheel aarch64 -> không compile.
# Nếu chưa cần, có thể COMMENT 2 dòng dưới để càng nhẹ.
RUN python3 -m pip install --no-cache-dir mediapipe>=0.10.0

# KHÔNG cài insightface khi build (để sau bằng script trong container).
# Nếu bạn thật sự muốn cài khi build (tốn RAM hơn), build với:
#   --build-arg WITH_FOLLOWME_EXTRAS=1
RUN if [ "x${WITH_FOLLOWME_EXTRAS}" = "x1" ]; then \
      python3 -m pip install --no-cache-dir onnxruntime-gpu==1.16.3 || python3 -m pip install --no-cache-dir onnxruntime==1.16.3; \
      python3 -m pip install --no-cache-dir insightface==0.7.3; \
    fi

# 5) Copy code & logs
COPY . .
RUN mkdir -p /app/logs

EXPOSE 9000

# 6) Quick sanity
RUN python3 - <<'PY'
import cv2, sys
print("[CHECK] OpenCV:", cv2.__version__)
try:
    import pyrealsense2 as rs
    print("[CHECK] pyrealsense2: OK")
except Exception as e:
    print("[WARN] pyrealsense2 import error:", e, file=sys.stderr)
try:
    import apriltag
    print("[CHECK] apriltag: OK (APT)")
except Exception as e:
    print("[INFO] apriltag not present:", e)
try:
    import mediapipe as mp
    print("[CHECK] mediapipe: OK")
except Exception as e:
    print("[INFO] mediapipe not present:", e)
PY

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000", "--log-level", "info"]
