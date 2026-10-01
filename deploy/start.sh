#!/bin/sh
set -eu
export PORT="${PORT:-10000}"
case "$PORT" in ''|*[!0-9]*) echo 'PORT must be numeric'; exit 1;; esac
if [ "${#API_TOKEN}" -lt 32 ] || [ "$API_TOKEN" = 'local-demo-change-me' ]; then
  echo 'Set a unique API_TOKEN with at least 32 characters.'; exit 1
fi
envsubst '${PORT}' < /app/deploy/nginx.conf.template > /tmp/nginx.conf
exec supervisord -n -c /app/deploy/supervisord.conf
