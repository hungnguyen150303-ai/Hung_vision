# Jetson / L4T r36.4.0 (JetPack 6.1)
FROM dustynv/l4t-pytorch:r36.4.0

# ==== build args / env để tiết kiệm RAM ====
ARG MAKE_JOBS=1
ARG USE_SRC_RS=0       # 0=apt librealsense, 1=build from source
ARG USE_PUPIL=0       # 0=apt python3-apriltag, 1=pupil-apriltags (pip build)
ENV MAKEFLAGS=-j${MAKE_JOBS} \
    CMAKE_BUILD_PARALLEL_LEVEL=${MAKE_JOBS} \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_DEFAULT_TIMEOUT=180 \
    RS_VER=v2.56.5 \
    GLOG_minloglevel=2 \
    TF_CPP_MIN_LOG_LEVEL=2 \
    # giảm RAM khi compile C/C++
    CFLAGS="-O2 -pipe -fno-lto" \
    CXXFLAGS="-O2 -pipe -fno-lto" \
    LDFLAGS="-fno-lto" \
    PIP_NO_BUILD_ISOLATION=1

# 1) Gói hệ thống chung (OpenCV system, Eigen cho apriltag)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config \
    libssl-dev libusb-1.0-0-dev libudev-dev \
    libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev \
    libeigen3-dev \
    udev v4l-utils ffmpeg curl ca-certificates \
    python3-opencv python3-pip \
 && rm -rf /var/lib/apt/lists/*

# 2) librealsense: ưu tiên APT (ít RAM). Có công tắc fallback build-from-source.
#    Lưu ý: nếu Intel repo không có gói arm64 phù hợp board của bạn, đổi USE_SRC_RS=1 khi build.
RUN set -e; \
 if [ "x${USE_SRC_RS}" = "x0" ]; then \
   echo ">>> Installing librealsense from Intel APT (no compile)"; \
   apt-get update && apt-get install -y --no-install-recommends gnupg software-properties-common && \
   curl -sS https://librealsense.intel.com/Debian/IntelRealSenseLFS.key | apt-key add - && \
   add-apt-repository "deb https://librealsense.intel.com/Debian/apt-repo jammy main" && \
   apt-get update && apt-get install -y --no-install-recommends \
     librealsense2 librealsense2-utils librealsense2-gl \
     python3-realsense2 \
   && rm -rf /var/lib/apt/lists/* || echo "[WARN] Intel APT may not provide arm64 on this image"; \
 else \
   echo ">>> Building librealsense from source (low-RAM flags)"; \
   cd /tmp && git clone --depth=1 --branch ${RS_VER} https://github.com/IntelRealSense/librealsense.git && \
   cd librealsense && mkdir build && cd build && \
   cmake .. \
     -DBUILD_EXAMPLES=OFF \
     -DBUILD_GRAPHICAL_EXAMPLES=OFF \
     -DBUILD_WITH_CUDA=OFF \ 
     -DBUILD_PYTHON_BINDINGS=ON \
     -DBUILD_TOOLS=OFF \
     -DBUILD_UNIT_TESTS=OFF \
     -DFORCE_RSUSB_BACKEND=ON \
     -DPYTHON_EXECUTABLE=/usr/bin/python3 && \
   make -j"${MAKE_JOBS}" && make install && ldconfig && \
   cp ../config/99-realsense-libusb.rules /etc/udev/rules.d/ || true && \
   udevadm control --reload-rules || true && \
   cd /tmp && rm -rf librealsense; \
 fi

# 3) AprilTag detector: ưu tiên apt (python3-apriltag). Công tắc fallback pupil-apriltags (pip build).
RUN set -e; \
 if [ "x${USE_PUPIL}" = "x0" ]; then \
   echo ">>> Installing python3-apriltag from APT"; \
   apt-get update && apt-get install -y --no-install-recommends \
     libapriltag3 python3-apriltag \
   && rm -rf /var/lib/apt/lists/*; \
 else \
   echo ">>> Installing pupil-apriltags (pip build; may use more RAM)"; \
   python3 -m pip install --no-cache-dir pupil-apriltags==1.0.4; \
 fi

# 4) App deps
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir -r /app/requirements.txt --no-deps \
 && python3 -m pip install --no-cache-dir "ultralytics>=8.2.0,<9" --no-deps \
 && python3 -m pip install --no-cache-dir fastapi "uvicorn[standard]" paho-mqtt

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
    print("[INFO] apriltag APT not present:", e)
try:
    import pupil_apriltags
    print("[CHECK] pupil_apriltags: OK (pip)")
except Exception as e:
    print("[INFO] pupil_apriltags not present:", e)
PY

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000", "--log-level", "info"]
