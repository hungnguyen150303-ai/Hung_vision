ARG MAKE_JOBS=1
ARG WITH_FOLLOWME_EXTRAS=0

FROM dustynv/l4t-pytorch:r36.4.0

ENV MAKEFLAGS="-j${MAKE_JOBS}" \
    CMAKE_BUILD_PARALLEL_LEVEL=${MAKE_JOBS} \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_DEFAULT_TIMEOUT=180 \
    GLOG_minloglevel=2 \
    TF_CPP_MIN_LOG_LEVEL=2 \
    PIP_PREFER_BINARY=1

# ==== Thêm kho APT RealSense (cách mới, tránh apt-key bị deprecated) ====
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates gnupg && \
    wget -O /usr/share/keyrings/librealsense-archive-keyring.gpg https://github.com/IntelRealSense/librealsense/raw/master/keys/IntelRealSenseLFS.key && \
    echo "deb [signed-by=/usr/share/keyrings/librealsense-archive-keyring.gpg] https://librealsense.intel.com/Debian/apt-repo jammy main" \
        > /etc/apt/sources.list.d/librealsense.list


# ==== Cài các gói hệ thống (gộp 1 RUN để tiết kiệm RAM/layer) ====
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config \
    libssl-dev libusb-1.0-0-dev libudev-dev \
    libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev \
    libeigen3-dev udev v4l-utils ffmpeg \
    python3-opencv python3-pip \
    python3-numpy python3-scipy python3-sklearn python3-sklearn-lib \
    python3-sympy python3-networkx python3-matplotlib python3-imageio \
    python3-pandas \
    librealsense2 librealsense2-utils librealsense2-gl python3-realsense2 \
 && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# ==== Cài thư viện Python ====
WORKDIR /app
COPY requirements.txt /app/requirements.txt

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir -r /app/requirements.txt --no-deps \
 && python3 -m pip install --no-cache-dir "ultralytics>=8.2.0,<9" --no-deps \
 && python3 -m pip install --no-cache-dir fastapi "uvicorn[standard]" paho-mqtt

# ==== Mediapipe (dùng trong gesture/unphysics) ====
RUN python3 -m pip install --no-cache-dir mediapipe>=0.10.0

# ==== InsightFace (chỉ khi build WITH_FOLLOWME_EXTRAS=1) ====
RUN if [ "x${WITH_FOLLOWME_EXTRAS}" = "x1" ]; then \
      python3 -m pip install --no-cache-dir onnxruntime-gpu==1.16.3 || python3 -m pip install --no-cache-dir onnxruntime==1.16.3; \
      python3 -m pip install --no-cache-dir insightface==0.7.3; \
    fi

# ==== Copy mã nguồn ====
COPY . .
RUN mkdir -p /app/logs

EXPOSE 9000

# ==== Sanity check ====
RUN python3 - <<'PY'
import cv2
print("[CHECK] OpenCV:", cv2.__version__)
try:
    import pyrealsense2 as rs
    print("[CHECK] pyrealsense2: OK")
except Exception as e:
    print("[WARN] pyrealsense2 import error:", e)
try:
    import mediapipe as mp
    print("[CHECK] mediapipe: OK")
except Exception as e:
    print("[WARN] mediapipe import error:", e)
PY

# ==== CMD chạy server ====
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000", "--log-level", "info"]
