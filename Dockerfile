# ===== Base image (khuyên dùng l4t-ml vì đã có ML stack) =====
ARG BASE_IMAGE=nvcr.io/nvidia/l4t-ml:r36.4.0-py3
# Hoặc nếu cần:
# ARG BASE_IMAGE=dustynv/l4t-pytorch:r36.4.0

ARG RS_VER=v2.56.5
ARG PORT=9000

# ===== Stage 1: build wheels nặng (làm một lần, cache lại) =====
FROM ${BASE_IMAGE} AS wheelsmith
SHELL ["/bin/bash","-eo","pipefail","-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config \
    python3-dev python3-pip python3-setuptools python3-wheel \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --upgrade pip wheel setuptools

WORKDIR /wheels
# Không cài opencv/pyrealsense2 từ pip
RUN python3 -m pip wheel \
      "ultralytics>=8.2.0,<9" \
      "onnxruntime==1.16.3" \
      "insightface==0.7.3" \
      "scipy==1.10.1" \
      "scikit-image==0.21.0" \
      "imageio>=2.31" "tifffile>=2023.7.10" "networkx>=2.8" "pillow>=9.5" \
      "albumentations==1.3.1" "qudida==0.0.4" \
      "scikit-learn==1.3.2" \
      -w /wheels

# ===== Stage 2: build librealsense (cache theo RS_VER) =====
FROM ${BASE_IMAGE} AS rsbuilder
SHELL ["/bin/bash","-eo","pipefail","-c"]
ARG RS_VER

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config \
    libssl-dev libusb-1.0-0-dev libudev-dev \
    libgtk-3-dev libglfw3-dev libgl1-mesa-dev libglu1-mesa-dev \
 && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y ccache && rm -rf /var/lib/apt/lists/*
ENV CCACHE_DIR=/root/.ccache CC="ccache gcc" CXX="ccache g++"

WORKDIR /tmp
RUN git clone --depth=1 --branch "${RS_VER}" https://github.com/IntelRealSense/librealsense.git \
 && cd librealsense && mkdir build && cd build \
 && cmake .. \
      -DBUILD_EXAMPLES=OFF \
      -DBUILD_GRAPHICAL_EXAMPLES=OFF \
      -DBUILD_WITH_CUDA=ON \
      -DBUILD_PYTHON_BINDINGS=ON \
      -DFORCE_RSUSB_BACKEND=ON \
      -DPYTHON_EXECUTABLE=/usr/bin/python3 \
 && make -j"$(nproc)" && make install \
 && cp ../config/99-realsense-libusb.rules /etc/udev/rules.d/ \
 && ldconfig

# ===== Stage 3: runtime =====
FROM ${BASE_IMAGE}
SHELL ["/bin/bash","-eo","pipefail","-c"]

ARG PORT
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen \
    PIP_INDEX_URL=https://pypi.org/simple \
    PIP_DEFAULT_TIMEOUT=180 \
    MPLBACKEND=Agg \
    PORT=${PORT}

# Gói hệ thống gọn
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-opencv python3-matplotlib \
    udev v4l-utils ffmpeg curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# librealsense từ stage 2
COPY --from=rsbuilder /usr/local/ /usr/local/
COPY --from=rsbuilder /etc/udev/rules.d/99-realsense-libusb.rules /etc/udev/rules.d/99-realsense-libusb.rules
RUN udevadm control --reload-rules || true && ldconfig

# dọn pip.conf nếu có
RUN rm -f /etc/pip.conf /root/.config/pip/pip.conf /root/.pip/pip.conf || true

WORKDIR /app

# 1) Cài wheel nặng (rất nhanh, không compile)
COPY --from=wheelsmith /wheels /tmp/wheels
RUN python3 -m pip install --no-index --find-links=/tmp/wheels \
      ultralytics onnxruntime insightface scipy scikit-image imageio tifffile networkx pillow \
      albumentations qudida scikit-learn \
 && rm -rf /tmp/wheels

# 2) Cài phần còn lại từ requirements (nhẹ)
COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip install --no-cache-dir -r /app/requirements.txt && \
    python3 - <<'PY'
import torch, cv2, sys
print("torch:", getattr(torch,'__version__',None),"cuda:",getattr(getattr(torch,'version',None),'cuda',None),"gpu:",getattr(torch,'cuda',None) and torch.cuda.is_available())
print("cv2:", cv2.__version__)
try:
    import pyrealsense2 as rs
    print("pyrealsense2: OK")
except Exception as e:
    print("pyrealsense2 import error:", e, file=sys.stderr)
PY

# 3) Copy code (đặt cuối để thay code không phá cache pip)
COPY . .
RUN mkdir -p /app/logs

EXPOSE ${PORT}
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS "http://127.0.0.1:${PORT}/docs" || exit 1
CMD ["sh","-c","uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
