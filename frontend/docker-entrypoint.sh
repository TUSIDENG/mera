#!/bin/sh
# M11：容器启动时生成 /config.js，向浏览器注入 Casdoor OIDC 运行时配置
#   CASDOOR_BROWSER_ENDPOINT：浏览器可达的 Casdoor 地址（默认 http://localhost:8000）
#   CASDOOR_CLIENT_ID：Casdoor 应用 Client ID
# 注意：Casdoor 应用需把 http://localhost:3000/callback 加入 Redirect URIs
set -eu

cat > /usr/share/nginx/html/config.js <<EOF
window.MERA_CONFIG={casdoorEndpoint:"${CASDOOR_BROWSER_ENDPOINT:-http://localhost:8000}",casdoorClientId:"${CASDOOR_CLIENT_ID:-}"};
EOF
