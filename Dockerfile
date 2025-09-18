FROM dustynv/l4t-pytorch:r36.4.0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_DEFAULT_TIMEOUT=180 \
    RS_VER=v2.56.5\
    MPLBACKEND=Agg

# 1) Gói hệ thống (OpenCV hệ thống + toolchain build librealsense)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config \
    libssl-dev libusb-1.0-0-dev libudev-dev \
    libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev \
    udev v4l-utils ffmpeg curl ca-certificates \
    python3-opencv python3-matplotlib \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp

# 2) Build librealsense từ source (CUDA + Python bindings)
RUN git clone --depth=1 --branch ${RS_VER} https://github.com/IntelRealSense/librealsense.git \
 && cd librealsense && mkdir build && cd build \
 && cmake .. \
      -DBUILD_EXAMPLES=OFF \
      -DBUILD_GRAPHICAL_EXAMPLES=OFF \
      -DBUILD_WITH_CUDA=ON \
      -DBUILD_PYTHON_BINDINGS=ON \
      -DFORCE_RSUSB_BACKEND=ON \
      -DPYTHON_EXECUTABLE=/usr/bin/python3 \
 && make -j"$(nproc)" \
 && make install \
 && cp ../config/99-realsense-libusb.rules /etc/udev/rules.d/ \
 && udevadm control --reload-rules || true \
 && ldconfig \
 && cd /tmp && rm -rf librealsense

# 3) Xóa pip.conf tùy biến (nếu có), đảm bảo dùng PyPI
RUN rm -f /etc/pip.conf /root/.config/pip/pip.conf /root/.pip/pip.conf || true

WORKDIR /app

# 4) Cài requirements (KHÔNG kéo opencv-python/pyrealsense2 từ pip)
COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
 && python3 -m pip install --no-cache-dir -r /app/requirements.txt \
 && python3 -m pip install --no-cache-dir "ultralytics>=8.2.0,<9" --no-deps\
 && python3 -m pip install --no-cache-dir "mediapipe==0.10.14" --no-deps


# 5) Kiểm tra cv2 / torch / pyrealsense2
RUN python3 - <<'PY'
import torch, cv2
print("torch:", torch.__version__, "cuda:", torch.version.cuda, "gpu:", torch.cuda.is_available())
print("cv2:", cv2.__version__)
try:
    import pyrealsense2 as rs
    print("pyrealsense2: OK")
except Exception as e:
    print("pyrealsense2 import error:", e)
PY

# 6) Copy code & cấu hình service
COPY . .
RUN mkdir -p /app/logs

EXPOSE 9000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000", "--proxy-headers"]
#CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9001"]