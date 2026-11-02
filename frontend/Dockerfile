# MERA 前端镜像：React 构建产物 + Nginx 托管（SPA + /api 反向代理 + 运行时注入 /config.js）
FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
# package-lock.json 随仓库提交，npm ci 保证可复现
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# 容器启动时生成 /config.js（window.MERA_CONFIG），注入浏览器侧 Casdoor 配置
COPY docker-entrypoint.sh /docker-entrypoint.d/40-mera-config.sh
RUN chmod +x /docker-entrypoint.d/40-mera-config.sh
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
