#!/usr/bin/env bash
set -e

APP_NAME="vision-service"
IMAGE_NAME="vision:jetson"

# ===== Host paths =====
BASE_DIR="/home/vetcbot/ServiceRobot/Vision"
LOG_DIR="$BASE_DIR/logs"
DATA_DIR="$BASE_DIR/data"
MODELS_DIR="$BASE_DIR/models"

# ===== Container paths =====
LOG_CONT_DIR="/app/logs"
DATA_CONT_DIR="/app/data"
MODELS_CONT_DIR="/app/models"

# ===== Port (default 9000) =====
PORT=$(python3 - <<'PY'
import json, os
port = 9000
try:
    if os.path.exists("config.json"):
        with open("config.json","r",encoding="utf-8") as f:
            port = int(json.load(f).get("PORT", 9000))
except Exception:
    pass
print(port)
PY
)

# ==== tuỳ chọn, kiểm soát song song & RAM khi build ====
BUILD_JOBS="${BUILD_JOBS:-1}"         # 1 = ít RAM nhất
BUILD_MEM="${BUILD_MEM:-4g}"          # giới hạn RAM 4GB
BUILD_MEMSWAP="${BUILD_MEMSWAP:-4g}"  # tổng RAM+swap cho build (đặt =4g để cứng; hoặc 6g để cho phép spike nhẹ)

echo "📦 Building image $IMAGE_NAME (jobs=$BUILD_JOBS, mem=$BUILD_MEM, swap=$BUILD_MEMSWAP) ..."
DOCKER_BUILDKIT=1 docker build \
  --build-arg MAKE_JOBS="$BUILD_JOBS" \
  --memory="$BUILD_MEM" --memory-swap="$BUILD_MEMSWAP" \
  -t "$IMAGE_NAME" .

# Tạo thư mục host nếu thiếu
mkdir -p "$LOG_DIR" "$DATA_DIR" "$MODELS_DIR"

echo "🛑 Stopping old container (if exists) ..."
docker rm -f "$APP_NAME" 2>/dev/null || true

echo "🚀 Running new container on port $PORT (host network) ..."
docker run -d \
  --name "$APP_NAME" \
  --runtime nvidia \
  --network host \
  --ipc=host \
  --privileged \
  -e QT_QPA_PLATFORM=offscreen \
  -e GLOG_minloglevel=2 \
  -e TF_CPP_MIN_LOG_LEVEL=2 \
  -v /dev:/dev \
  -v /run/udev:/run/udev:ro \
  -v "$LOG_DIR":"$LOG_CONT_DIR" \
  -v "$DATA_DIR":"$DATA_CONT_DIR" \
  -v "$MODELS_DIR":"$MODELS_CONT_DIR" \
  "$IMAGE_NAME"

echo "✅ Up. Logs:  docker logs -f $APP_NAME"
echo "🌐 Test:     curl http://127.0.0.1:$PORT/healthz"
echo "📁 Logs:     $LOG_DIR"
echo "📁 Data:     $DATA_DIR"
