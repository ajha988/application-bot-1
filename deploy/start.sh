#!/bin/sh
set -eu

# 1. Fallback port if Back4app doesn't pass one dynamically
export PORT="${PORT:-10000}"

# 2. Validate numeric PORT
case "$PORT" in 
  ''|*[!0-9]*) 
    echo 'PORT must be numeric'; 
    exit 1
    ;;
esac

# 3. Validate API_TOKEN length and check default value
if [ "${#API_TOKEN}" -lt 32 ] || [ "$API_TOKEN" = 'local-demo-change-me' ]; then
  echo 'Set a unique API_TOKEN with at least 32 characters.'
  exit 1
fi

# 4. Substitute both $PORT and ${PORT} while preserving other Nginx variables ($host, $scheme, etc.)
envsubst '$PORT ${PORT}' < /app/deploy/nginx.conf.template > /tmp/nginx.conf

# 5. Start Supervisor to manage processes inside the container
exec supervisord -n -c /app/deploy/supervisord.conf