#!/usr/bin/env bash
set -e

APP_NAME="vision-service"
IMAGE_NAME="vision:jetson"

# ===== Host paths (sửa theo ý bạn) =====
BASE_DIR="/home/vetcbot/ServiceRobot/Vision"
LOG_DIR="/home/vetcbot/ServiceRobot/logs/VISION"
DATA_DIR="$BASE_DIR/data"               # nếu muốn lưu data
MODELS_DIR="$BASE_DIR/models"           # nếu code có models

# ===== Container paths =====
LOG_CONT_DIR="/app/logs"
DATA_CONT_DIR="/app/data"
MODELS_CONT_DIR="/app/models"

# ===== Port (default 9000 hoặc từ config.json) =====
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

echo "📦 Building image $IMAGE_NAME ..."
docker build -t "$IMAGE_NAME" .

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
