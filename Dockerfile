ARG MAKE_JOBS=1
ARG WITH_FOLLOWME_EXTRAS=0  # 0 = chưa cài insightface khi build

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

# ==== Cài các gói hệ thống cần thiết (gộp vào 1 RUN) ====
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config \
    libssl-dev libusb-1.0-0-dev libudev-dev \
    libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev \
    libeigen3-dev udev v4l-utils ffmpeg curl ca-certificates \
    python3-opencv python3-pip \
    python3-numpy python3-scipy python3-sklearn python3-sklearn-lib \
    python3-sympy python3-networkx python3-matplotlib python3-imageio \
    python3-pandas \
 && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# ==== Cài các thư viện Python cơ bản ====
WORKDIR /app
COPY requirements.txt /app/requirements.txt

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir -r /app/requirements.txt --no-deps \
 && python3 -m pip install --no-cache-dir "ultralytics>=8.2.0,<9" --no-deps \
 && python3 -m pip install --no-cache-dir fastapi "uvicorn[standard]" paho-mqtt

# ==== Mediapipe (nếu cần dùng trong unphysics) ====
RUN python3 -m pip install --no-cache-dir mediapipe>=0.10.0

# ==== InsightFace (nếu build WITH_FOLLOWME_EXTRAS=1) ====
RUN if [ "x${WITH_FOLLOWME_EXTRAS}" = "x1" ]; then \
      python3 -m pip install --no-cache-dir onnxruntime-gpu==1.16.3 || python3 -m pip install --no-cache-dir onnxruntime==1.16.3; \
      python3 -m pip install --no-cache-dir insightface==0.7.3; \
    fi

# ==== Copy mã nguồn ====
COPY . .
RUN mkdir -p /app/logs

EXPOSE 9000

# ==== Sanity check (có thể giữ lại hoặc bỏ) ====
RUN python3 - <<'PY'
import cv2
print("[CHECK] OpenCV:", cv2.__version__)
try:
    import mediapipe as mp
    print("[CHECK] mediapipe: OK")
except Exception as e:
    print("[WARN] mediapipe import error:", e)
PY

# ==== Lệnh khởi chạy app ====
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000", "--log-level", "info"]
