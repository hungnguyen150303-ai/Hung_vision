#!/usr/bin/env bash
set -euo pipefail

APP_NAME="vision-service"
IMAGE_NAME="vision:jetson"

# ===== Host paths =====
BASE_DIR="/home/vetcbot/ServiceRobot/Vision"
LOG_DIR="/home/vetcbot/ServiceRobot/logs/VISION"
DATA_DIR="$BASE_DIR/data"
MODELS_DIR="$BASE_DIR/models"

# ===== Container paths =====
LOG_CONT_DIR="/app/logs"
DATA_CONT_DIR="/app/data"
MODELS_CONT_DIR="/app/models"

# ===== Base image để build (có thể override khi chạy) =====
# Ví dụ: BASE_IMAGE="nvcr.io/nvidia/l4t-ml:r36.4.0-py3" ./run_vision.sh
BASE_IMAGE="${BASE_IMAGE:-dustynv/l4t-pytorch:r36.4.0}"

# ===== Helper: retry pull với backoff =====
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

# ===== Chuẩn bị =====
echo "📂 cd $BASE_DIR"
cd "$BASE_DIR"

# Sync clock (tránh lỗi TLS do lệch giờ, thường gặp trên Jetson)
if command -v timedatectl >/dev/null 2>&1; then
  sudo timedatectl set-ntp true || true
fi

# Lấy PORT từ config.json trong BASE_DIR (mặc định 9000)
PORT=$(python3 - <<'PY'
import json, os
port = 9000
try:
    cfg = os.path.join(os.getcwd(), "config.json")
    if os.path.exists(cfg):
        with open(cfg, "r", encoding="utf-8") as f:
            port = int(json.load(f).get("PORT", 9000))
except Exception:
    pass
print(port)
PY
)

# Tạo thư mục host nếu thiếu
mkdir -p "$LOG_DIR" "$DATA_DIR" "$MODELS_DIR"

# ===== Bảo đảm base image sẵn sàng (tự pull nếu chưa có) =====
if ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
  echo "🧩 Base image not found locally: $BASE_IMAGE"
  docker_pull_retry "$BASE_IMAGE"
fi

# ===== Build app image (truyền BASE_IMAGE vào Dockerfile) =====
echo "📦 Building image $IMAGE_NAME (BASE_IMAGE=$BASE_IMAGE) ..."
# --pull=true để refresh metadata base (nếu mạng ổn)
DOCKER_BUILDKIT=1 docker build \
  --pull \
  --build-arg BASE_IMAGE="$BASE_IMAGE" \
  -t "$IMAGE_NAME" .

# ===== Restart container =====
echo "🛑 Stopping old container (if exists) ..."
docker rm -f "$APP_NAME" 2>/dev/null || true

echo "🚀 Running new container on port $PORT (host network) ..."
docker run -d \
  --name "$APP_NAME" \
  --runtime nvidia \
  --network host \
  --ipc=host \
  --privileged \
  --restart unless-stopped \
  -e QT_QPA_PLATFORM=offscreen \
  -e PORT="$PORT" \
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
