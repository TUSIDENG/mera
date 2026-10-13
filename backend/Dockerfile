# MERA 后端镜像：FastAPI + Celery（backend-app / worker / beat / flower 共用）
FROM python:3.12-slim

ARG INSTALL_PLAYWRIGHT=false
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# 浏览器采集策略所需：Playwright + Chromium 及系统依赖
# 通过构建参数 INSTALL_PLAYWRIGHT=true 开启（docker-compose 本地部署默认开启）
RUN if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then \
        pip install playwright \
        && python -m playwright install --with-deps chromium; \
    fi

COPY . .

RUN chmod +x /app/scripts/start-backend.sh

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
