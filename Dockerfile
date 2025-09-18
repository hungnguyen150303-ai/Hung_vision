# ===== 0) Base image linh hoạt (mặc định dùng l4t-pytorch r36.4.0) =====
ARG BASE_IMAGE=dustynv/l4t-pytorch:r36.4.0
FROM ${BASE_IMAGE}

# Dùng bash + pipefail cho các RUN dài
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

# ===== 1) ENV chung =====
ARG PORT=9000
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_DEFAULT_TIMEOUT=180 \
    RS_VER=v2.56.5 \
    MPLBACKEND=Agg \
    PORT=${PORT}

# ===== 2) Gói hệ thống (OpenCV hệ thống + toolchain build librealsense) =====
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config \
    libssl-dev libusb-1.0-0-dev libudev-dev \
    libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev \
    udev v4l-utils ffmpeg curl ca-certificates \
    python3-opencv python3-matplotlib \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp

# ===== 3) Build librealsense từ source (CUDA + Python bindings) =====
# Lưu ý: bạn đang chạy container với --privileged + mount /dev, nên udev rules có hiệu lực
RUN git clone --depth=1 --branch "${RS_VER}" https://github.com/IntelRealSense/librealsense.git \
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

# ===== 4) Dọn pip.conf tuỳ biến (nếu có) để chắc chắn dùng PyPI =====
RUN rm -f /etc/pip.conf /root/.config/pip/pip.conf /root/.pip/pip.conf || true

WORKDIR /app

# ===== 5) Cài requirements (không cài opencv/pyrealsense2 từ pip) =====
COPY requirements.txt /app/requirements.txt

# Bật BuildKit mount cache nếu có; nếu không có cũng vẫn chạy bình thường
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip install --no-cache-dir -r /app/requirements.txt && \
    python3 -m pip install --no-cache-dir "ultralytics>=8.2.0,<9" --no-deps && \
    python3 -m pip install --no-cache-dir "mediapipe==0.10.14" --no-deps && \
    python3 -m pip install --no-cache-dir "onnxruntime==1.16.3" && \
    python3 -m pip install --no-cache-dir "insightface==0.7.3" --no-deps && \
    python3 -m pip install --no-cache-dir \
      "scipy==1.10.1" \
      "scikit-image==0.21.0" \
      "imageio>=2.31" "tifffile>=2023.7.10" "networkx>=2.8" "pillow>=9.5" && \
    python3 -m pip install --no-cache-dir "albumentations==1.3.1" --no-deps && \
    python3 -m pip install --no-cache-dir "qudida==0.0.4" --no-deps && \
    python3 -m pip install --no-cache-dir "scikit-learn==1.3.2"

# ===== 6) Kiểm tra cv2 / torch / pyrealsense2 =====
RUN python3 - <<'PY'
import torch, cv2, sys
print("torch:", torch.__version__, "cuda:", getattr(torch.version, "cuda", None), "gpu:", torch.cuda.is_available())
print("cv2:", cv2.__version__)
try:
    import pyrealsense2 as rs  # noqa
    print("pyrealsense2: OK")
except Exception as e:
    print("pyrealsense2 import error:", e, file=sys.stderr)
PY

# ===== 7) Copy code & chuẩn bị thư mục =====
COPY . .
RUN mkdir -p /app/logs

# ===== 8) Healthcheck & cổng =====
EXPOSE ${PORT}
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS "http://127.0.0.1:${PORT}/docs" || exit 1

# ===== 9) Entrypoint =====
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
