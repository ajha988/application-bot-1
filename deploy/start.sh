#!/bin/sh
set -eu

# 1. Fallback port if Back4app doesn't pass one dynamically (matches Back4app 8000/tcp configuration)
export PORT="${PORT:-8000}"

# 2. Validate numeric PORT
case "$PORT" in 
  ''|*[!0-9]*) 
    echo "ERROR: PORT must be numeric. Received: '$PORT'" >&2
    exit 1
    ;;
esac

# 3. Safely validate API_TOKEN under 'set -u'
API_TOKEN="${API_TOKEN:-}"
if [ "${#API_TOKEN}" -lt 32 ] || [ "$API_TOKEN" = 'local-demo-change-me' ]; then
  echo 'ERROR: Set a unique API_TOKEN with at least 32 characters in Back4app Environment Variables.' >&2
  exit 1
fi

# 4. Substitute ONLY $PORT / ${PORT} into /tmp/nginx.conf, preserving all internal Nginx variables
envsubst '$PORT' < /app/deploy/nginx.conf.template > /tmp/nginx.conf

# 5. Start Supervisor in non-daemon mode
exec supervisord -n -c /app/deploy/supervisord.conf