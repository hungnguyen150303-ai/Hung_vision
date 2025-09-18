#!/usr/bin/env bash
set -euo pipefail

# ================== Config cơ bản (đổi nếu cần) ==================
APP_NAME="vision-service"
IMAGE_NAME="vision:jetson"

BASE_DIR="/home/vetcbot/ServiceRobot/Vision"
LOG_DIR="/home/vetcbot/ServiceRobot/logs/VISION"
DATA_DIR="$BASE_DIR/data"
MODELS_DIR="$BASE_DIR/models"

# Mount trong container
LOG_CONT_DIR="/app/logs"
DATA_CONT_DIR="/app/data"
MODELS_CONT_DIR="/app/models"

# Base image & phiên bản librealsense (cho Dockerfile)
: "${BASE_IMAGE:=nvcr.io/nvidia/l4t-ml:r36.4.0-py3}"   # hoặc: dustynv/l4t-pytorch:r36.4.0
: "${RS_VER:=v2.56.5}"

# Giới hạn tài nguyên
: "${MAX_RAM:=4g}"         # tổng RAM container
: "${SHM_SIZE:=512m}"      # dung lượng /dev/shm

# ================== Helper ==================
docker_pull_retry() {
  local img="$1" max=4 delay=3
  for i in $(seq 1 "$max"); do
    echo "➡️  [${i}/${max}] pulling $img ..."
    if docker pull "$img"; then
      echo "✅ Pulled $img"
      return 0
    fi
    echo "⚠️  Pull failed, retry in ${delay}s..."
    sleep "$delay"
    delay=$((delay * 2))
  done
  echo "❌ Could not pull $img after $max attempts."
  return 1
}

# ================== Chuẩn bị ==================
echo "📂 cd $BASE_DIR"
cd "$BASE_DIR"

# Đồng bộ giờ (tránh TLS handshake timeout vì clock skew)
if command -v timedatectl >/dev/null 2>&1; then
  sudo timedatectl set-ntp true || true
fi

# Lấy PORT từ config.json (mặc định 9000)
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
echo "🌐 Service PORT = $PORT"

# Thư mục cần thiết
mkdir -p "$LOG_DIR" "$DATA_DIR" "$MODELS_DIR" .docker-cache

# ================== Pre-pull base image (retry) ==================
echo "⤵️  Pre-pull base image: $BASE_IMAGE"
docker_pull_retry "$BASE_IMAGE" || true

# ================== Build (buildx + docker-container driver + cache) ==================
echo "🔧 Ensuring buildx builder..."
if ! docker buildx inspect vbuilder >/dev/null 2>&1; then
  docker buildx create --name vbuilder --use --driver docker-container
else
  docker buildx use vbuilder
fi

echo "📦 Building $IMAGE_NAME (BASE_IMAGE=$BASE_IMAGE, RS_VER=$RS_VER, PORT=$PORT) ..."
docker buildx build \
  --builder vbuilder \
  --build-arg BASE_IMAGE="$BASE_IMAGE" \
  --build-arg RS_VER="$RS_VER" \
  --build-arg PORT="$PORT" \
  --cache-from type=local,src=.docker-cache \
  --cache-to   type=local,dest=.docker-cache,mode=max \
  -t "$IMAGE_NAME" \
  --load \
  "$BASE_DIR"

# ================== Run container (giới hạn RAM & giảm thread) ==================
echo "🛑 Removing old container (if exists) ..."
docker rm -f "$APP_NAME" 2>/dev/null || true

echo "🚀 Running container on port $PORT with RAM limit ~$MAX_RAM ..."
docker run -d \
  --name "$APP_NAME" \
  --runtime nvidia \
  --network host \
  --privileged \
  --restart unless-stopped \
  \
  --memory="$MAX_RAM" \
  --memory-swap="$MAX_RAM" \
  --shm-size="$SHM_SIZE" \
  \
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
  -v /dev:/dev \
  -v /run/udev:/run/udev:ro \
  -v "$LOG_DIR":"$LOG_CONT_DIR" \
  -v "$DATA_DIR":"$DATA_CONT_DIR" \
  -v "$MODELS_DIR":"$MODELS_CONT_DIR" \
  "$IMAGE_NAME"

echo "✅ Up. Logs:  docker logs -f $APP_NAME"
echo "🌐 Test:     curl http://127.0.0.1:$PORT/docs"
echo "📁 Logs:     $LOG_DIR"
echo "📁 Data:     $DATA_DIR"
echo "⚙️  Change RAM: set MAX_RAM / SHM_SIZE or edit script."
