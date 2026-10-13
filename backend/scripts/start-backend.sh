#!/bin/sh
# backend-app 容器入口：先执行数据库迁移，再启动 FastAPI
set -e

# 存在 Alembic 迁移配置时自动升级表结构（UUID v7 扩展、表与 RLS 策略等）
if [ -f "/app/alembic.ini" ]; then
    echo "[start-backend] running alembic upgrade head ..."
    alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
