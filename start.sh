#!/bin/sh
set -eu
: "${PORT:=8080}"
: "${APP_PORT:=5000}"
: "${XRAY_PORT:=10000}"
: "${DATA_DIR:=/app/data}"
mkdir -p "$DATA_DIR" /run/nginx
export PORT APP_PORT XRAY_PORT DATA_DIR
# Importing the app initializes the persistent schema and writes Xray/Nginx configs.
python -c 'import app; app.init(); app.regenerate()'
# Keep Nginx configuration in the generated persistent location.
rm -f /etc/nginx/sites-enabled/default
ln -sf "$DATA_DIR/nginx/default.conf" /etc/nginx/conf.d/titan.conf
# Start the internal web application.
gunicorn --chdir /app --workers 2 --threads 4 --timeout 120 --bind 127.0.0.1:${APP_PORT} app:app &
APP_PID=$!
# Start Xray only when its binary is present; the web panel remains available if it cannot start.
if command -v xray >/dev/null 2>&1; then
  xray run -config "$DATA_DIR/xray/config.json" >>"$DATA_DIR/xray/xray.log" 2>&1 & XRAY_PID=$!
else
  XRAY_PID=""
fi
nginx -g 'daemon off;' & NGINX_PID=$!
term(){ kill "$NGINX_PID" "$APP_PID" ${XRAY_PID:-} 2>/dev/null || true; wait || true; }
trap term INT TERM EXIT
wait "$NGINX_PID"
