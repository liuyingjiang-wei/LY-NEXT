# 一键启动 LY-NEXT Docker Demo（Redis + PostgreSQL + App）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host "已创建 docker/.env（请按需填写 OPENAI_API_KEY 等）"
}

docker compose -f docker-compose.yml --profile app up -d --build

$port = if ($env:LY_NEXT_PORT) { $env:LY_NEXT_PORT } else { "8000" }
Write-Host ""
Write-Host "=== LY-NEXT Docker Demo ==="
Write-Host "工作台:  http://127.0.0.1:$port/ly/login"
Write-Host "OpenAPI: http://127.0.0.1:$port/docs"
Write-Host ""
Write-Host "API 密钥: docker exec ly-next-app cat /app/data/ly_next/FIRST_RUN.txt"
Write-Host "诊断:     docker exec ly-next-app ly doctor"
Write-Host ""
Write-Host "停止: docker compose -f docker/docker-compose.yml --profile app down"
