#!/usr/bin/env bash
# Shell 一键启动全套智能 RAG 系统脚本 (支持 Linux / macOS)

set -Eeuo pipefail

# 项目路径定义
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/Backend"
FRONTEND_DIR="$ROOT_DIR/Frontend"
COMPOSE_FILE="$BACKEND_DIR/docker-compose.yml"
ENV_FILE="$BACKEND_DIR/.env"
STOP_DATA_ON_EXIT=0
DATA_SERVICES_STARTED=0
PIDS=()

if [[ "${1:-}" == "--stop-data" ]]; then
  STOP_DATA_ON_EXIT=1
elif [[ $# -gt 0 ]]; then
  echo "用法: ./start.sh [--stop-data]" >&2
  exit 2
fi

log() {
  printf '\n[start] %s\n' "$1"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "错误: 未找到命令 '$1'。$2" >&2
    exit 1
  fi
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  if (( ${#PIDS[@]} > 0 )); then
    log "正在停止前端、API 和 Worker..."
    kill "${PIDS[@]}" 2>/dev/null || true
    wait "${PIDS[@]}" 2>/dev/null || true
  fi

  if (( DATA_SERVICES_STARTED == 1 && STOP_DATA_ON_EXIT == 1 )); then
    log "正在停止 Docker 数据服务（数据卷会保留）..."
    compose stop mysql redis etcd minio milvus || true
  elif (( DATA_SERVICES_STARTED == 1 )); then
    echo "[start] Docker 数据服务继续在后台运行。"
  fi

  exit "$exit_code"
}

# 信号捕获与清理函数绑定
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 检查基础依赖
require_command docker "请先安装并启动 Docker Desktop。"
require_command uv "请先安装 uv: https://docs.astral.sh/uv/"
require_command npm "请先安装 Node.js（其中包含 npm）。"

if ! docker info >/dev/null 2>&1; then
  echo "错误: Docker 守护进程未运行，请先启动 Docker Desktop。" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "错误: 当前 Docker 未安装 Compose v2 插件。" >&2
  exit 1
fi

# 配置文件检查与生成
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$BACKEND_DIR/.env.example" ]]; then
    cp "$BACKEND_DIR/.env.example" "$ENV_FILE"
    echo "已创建 Backend/.env，请填写数据库密码、JWT 密钥和模型配置后重新运行。" >&2
  else
    echo "错误: 缺少 Backend/.env。" >&2
  fi
  exit 1
fi

log "启动并等待 MySQL、Redis、etcd、MinIO 和 Milvus..."
DATA_SERVICES_STARTED=1
compose up -d --wait mysql redis etcd minio milvus

log "同步 uv 后端依赖并执行 Alembic 迁移..."
(
  cd "$BACKEND_DIR"
  uv sync
  uv run alembic upgrade head
)

if [[ ! -x "$FRONTEND_DIR/node_modules/.bin/vite" ]]; then
  log "安装前端依赖..."
  (
    cd "$FRONTEND_DIR"
    npm ci
  )
fi

log "启动 FastAPI、文档 Worker 和 Vue 前端..."
echo "  前端:   http://localhost:5173"
echo "  API:    http://localhost:8000"
echo "  Swagger:http://localhost:8000/docs"
echo "  Milvus: http://localhost:9091/healthz"
echo "  按 Ctrl+C 停止应用进程。"

(
  cd "$BACKEND_DIR"
  exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
) &
PIDS+=("$!")

(
  cd "$BACKEND_DIR"
  exec uv run python -m app.worker
) &
PIDS+=("$!")

(
  cd "$FRONTEND_DIR"
  exec npm run dev -- --host 0.0.0.0 --port 5173
) &
PIDS+=("$!")

# 监控子进程，当任意服务意外退出时触发清理退出
while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      if wait "$pid"; then
        exit 0
      else
        exit $?
      fi
    fi
  done
  sleep 2
done
