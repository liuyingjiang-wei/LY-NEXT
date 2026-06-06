#!/usr/bin/env bash
# 一键启动 LY-NEXT Docker Demo（Redis + PostgreSQL + App）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/docker"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已创建 docker/.env（请按需填写 OPENAI_API_KEY 等）"
fi

docker compose -f docker-compose.yml --profile app up -d --build

echo ""
echo "=== LY-NEXT Docker Demo ==="
echo "工作台:  http://127.0.0.1:${LY_NEXT_PORT:-8000}/ly/login"
echo "OpenAPI: http://127.0.0.1:${LY_NEXT_PORT:-8000}/docs"
echo ""
echo "API 密钥: docker exec ly-next-app cat /app/data/ly_next/FIRST_RUN.txt 2>/dev/null || docker logs ly-next-app | head -n 40"
echo "诊断:     docker exec ly-next-app ly doctor"
echo ""
echo "停止: docker compose -f docker/docker-compose.yml --profile app down"
