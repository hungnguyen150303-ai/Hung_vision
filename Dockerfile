# Jetson / L4T r36.4.0 (JetPack 6.1)
FROM dustynv/l4t-pytorch:r36.4.0

# ==== kiểm soát mức song song khi build (giảm RAM) ====
ARG MAKE_JOBS=1
ENV MAKEFLAGS=-j${MAKE_JOBS} \
    CMAKE_BUILD_PARALLEL_LEVEL=${MAKE_JOBS}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_DEFAULT_TIMEOUT=180 \
    RS_VER=v2.56.5 \
    GLOG_minloglevel=2 \
    TF_CPP_MIN_LOG_LEVEL=2

# 1) Gói hệ thống (OpenCV system + build librealsense + eigen cho AprilTag)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config \
    libssl-dev libusb-1.0-0-dev libudev-dev \
    libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev \
    libeigen3-dev \
    udev v4l-utils ffmpeg curl ca-certificates \
    python3-opencv \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp

# 2) Build librealsense (tôn trọng MAKE_JOBS)
RUN git clone --depth=1 --branch ${RS_VER} https://github.com/IntelRealSense/librealsense.git \
 && cd librealsense && mkdir build && cd build \
 && cmake .. \
      -DBUILD_EXAMPLES=OFF \
      -DBUILD_GRAPHICAL_EXAMPLES=OFF \
      -DBUILD_WITH_CUDA=ON \
      -DBUILD_PYTHON_BINDINGS=ON \
      -DFORCE_RSUSB_BACKEND=ON \
      -DPYTHON_EXECUTABLE=/usr/bin/python3 \
 && make -j"${MAKE_JOBS}" \
 && make install \
 && cp ../config/99-realsense-libusb.rules /etc/udev/rules.d/ \
 && udevadm control --reload-rules || true \
 && ldconfig \
 && cd /tmp && rm -rf librealsense

# 3) Xoá pip.conf tùy biến
RUN rm -f /etc/pip.conf /root/.config/pip/pip.conf /root/.pip/pip.conf || true

# 4) App
WORKDIR /app
COPY requirements.txt /app/requirements.txt

# 5) Python deps (tránh build song song quá mức nhờ ENV ở trên)
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir -r /app/requirements.txt --no-deps \
 && python3 -m pip install --no-cache-dir "ultralytics>=8.2.0,<9" --no-deps \
 && python3 -m pip install --no-cache-dir fastapi "uvicorn[standard]" paho-mqtt \
 && python3 -m pip install --no-cache-dir pupil-apriltags==1.0.4

# 6) Copy code & logs
COPY . .
RUN mkdir -p /app/logs

EXPOSE 9000

# 7) Quick sanity
RUN python3 - <<'PY'
import cv2, sys
print("[CHECK] OpenCV:", cv2.__version__)
try:
    import pyrealsense2 as rs
    print("[CHECK] pyrealsense2: OK")
except Exception as e:
    print("[WARN] pyrealsense2 import error:", e, file=sys.stderr)
PY

# 8) Run
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000", "--log-level", "info"]
