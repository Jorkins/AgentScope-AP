# AgentScope-AP 一键启动（PowerShell）
# 用法：右键用 PowerShell 运行，或终端执行  ./start.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==> 启动依赖环境 (PostgreSQL/Redis/Milvus/MinIO)" -ForegroundColor Cyan
docker compose -f "$root/docker-compose.yml" up -d postgres redis milvus minio minio-init

if (-not (Test-Path "$root/.env")) {
    Copy-Item "$root/.env.example" "$root/.env"
    Write-Host "==> 已生成 .env，请填入模型 API Key 后重跑" -ForegroundColor Yellow
}

Write-Host "==> 串行升级 AP 与 AgentScope 数据库 schema" -ForegroundColor Cyan
Push-Location "$root/backend"
try {
    & ".venv/Scripts/python.exe" -m scripts.migrate_db
    if ($LASTEXITCODE -ne 0) {
        throw "数据库迁移失败，停止启动后端"
    }
} finally {
    Pop-Location
}

Write-Host "==> 启动后端 (http://localhost:8000)" -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "cd '$root/backend'; .venv/Scripts/python -m app.main"
)

Write-Host "==> 启动前端 (http://localhost:5173)" -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    '-NoExit', '-Command',
    "cd '$root/frontend'; pnpm dev"
)

Write-Host "完成。后端 http://localhost:8000  前端 http://localhost:5173" -ForegroundColor Green
