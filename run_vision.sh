#!/usr/bin/env bash
set -euo pipefail

APP_NAME="vision-service"
IMAGE_NAME="vision:jetson"

# ===== Paths (sửa nếu cần) =====
BASE_DIR="/home/vetcbot/ServiceRobot/Vision"
LOG_DIR="/home/vetcbot/ServiceRobot/logs/VISION"
DATA_DIR="$BASE_DIR/data"
MODELS_DIR="$BASE_DIR/models"

# ===== Container mount points =====
LOG_CONT_DIR="/app/logs"
DATA_CONT_DIR="/app/data"
MODELS_CONT_DIR="/app/models"

# ===== Base image & phiên bản librealsense (override qua env nếu muốn) =====
: "${BASE_IMAGE:=nvcr.io/nvidia/l4t-ml:r36.4.0-py3}"   # hoặc: dustynv/l4t-pytorch:r36.4.0
: "${RS_VER:=v2.56.5}"

# ===== Lấy PORT từ config.json trong BASE_DIR (mặc định 9000) =====
cd "$BASE_DIR"
PORT=$(python3 - <<'PY'
import json, os
port=9000
cfg="config.json"
try:
    if os.path.exists(cfg):
        with open(cfg,"r",encoding="utf-8") as f:
            port=int(json.load(f).get("PORT",9000))
except: pass
print(port)
PY
)

# ===== Chuẩn bị thư mục và cache local =====
mkdir -p "$LOG_DIR" "$DATA_DIR" "$MODELS_DIR" .docker-cache

# ===== Đồng bộ clock (tránh lỗi TLS) =====
if command -v timedatectl >/dev/null 2>&1; then
  sudo timedatectl set-ntp true || true
fi

# ===== Pre-pull base image để đỡ “load metadata” timeout =====
echo "⤵️  Pre-pull base image: $BASE_IMAGE"
docker pull "$BASE_IMAGE" || true

# ===== Build image với BuildKit + cache local =====
echo "📦 Building $IMAGE_NAME (BASE_IMAGE=$BASE_IMAGE, RS_VER=$RS_VER, PORT=$PORT) ..."
DOCKER_BUILDKIT=1 docker buildx build \
  --build-arg BASE_IMAGE="$BASE_IMAGE" \
  --build-arg RS_VER="$RS_VER" \
  --build-arg PORT="$PORT" \
  --cache-from type=local,src=.docker-cache \
  --cache-to   type=local,dest=.docker-cache,mode=max \
  -t "$IMAGE_NAME" \
  "$BASE_DIR"

# ===== Restart container =====
echo "🛑 Removing old container (if exists) ..."
docker rm -f "$APP_NAME" 2>/dev/null || true

echo "🚀 Running container on port $PORT with ~4GB RAM limit ..."
docker run -d \
  --name "$APP_NAME" \
  --runtime nvidia \
  --network host \
  --privileged \
  --restart unless-stopped \
  \
  # ==== Giới hạn bộ nhớ ====
  --memory=4g \
  --memory-swap=4g \
  --shm-size=512m \
  \
  # ==== Env: giảm thread & RAM ====
  -e QT_QPA_PLATFORM=offscreen \
  -e PORT="$PORT" \
  -e OMP_NUM_THREADS=1 \
  -e OPENBLAS_NUM_THREADS=1 \
  -e MKL_NUM_THREADS=1 \
  -e NUMEXPR_NUM_THREADS=1 \
  -e NUMBA_NUM_THREADS=1 \
  -e MALLOC_ARENA_MAX=2 \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:False,max_split_size_mb:64 \
  -e ORT_NUM_THREADS=1 \
  \
  # ==== Thiết bị & udev ====
  -v /dev:/dev \
  -v /run/udev:/run/udev:ro \
  \
  # ==== Mount logs/data/models ====
  -v "$LOG_DIR":"$LOG_CONT_DIR" \
  -v "$DATA_DIR":"$DATA_CONT_DIR" \
  -v "$MODELS_DIR":"$MODELS_CONT_DIR" \
  "$IMAGE_NAME"

echo "✅ Up. Logs:  docker logs -f $APP_NAME"
echo "🌐 Test:     curl http://127.0.0.1:$PORT/docs"
echo "📁 Logs:     $LOG_DIR"
echo "📁 Data:     $DATA_DIR"
echo "⚙️  Change RAM limit: edit --memory/--shm-size in run_vision.sh"
