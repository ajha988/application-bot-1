FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DISPLAY=:99 DATA_DIR=/data APP_ENV=production REMOTE_DESKTOP_ENABLED=true DESKTOP_SECURE_COOKIE=true
RUN apt-get update && apt-get install -y --no-install-recommends nginx xvfb fluxbox x11vnc novnc websockify supervisor gettext-base && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && python -m playwright install --with-deps chromium
COPY backend/ /app/backend/
COPY sample-profile.json sample-jobs.json /app/
COPY --from=frontend /build/dist /app/frontend/dist
COPY deploy/ /app/deploy/
RUN useradd --create-home --uid 10001 bot && mkdir -p /data /tmp/nginx-client /tmp/nginx-proxy && chown -R bot:bot /data /app /tmp/nginx-client /tmp/nginx-proxy && chmod +x /app/deploy/start.sh
USER bot
EXPOSE 10000
CMD ["/bin/sh", "/app/deploy/start.sh"]
