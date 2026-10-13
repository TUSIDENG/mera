#!/bin/sh
# M01 冒烟脚本：容器/本地启动 uvicorn 并探测 /healthz（依赖已安装时直接运行）
set -e

uvicorn app.main:app --host 127.0.0.1 --port 8000 >/tmp/uvi.log 2>&1 &
UVI_PID=$!
sleep 4

python - <<'EOF'
import urllib.request

body = urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=5).read().decode()
print("HEALTHZ:", body)
assert '"status":"ok"' in body or '"status": "ok"' in body, "unexpected healthz body"
EOF

echo "[smoke] uvicorn /healthz OK"
head -n 5 /tmp/uvi.log
kill "$UVI_PID" 2>/dev/null || true
