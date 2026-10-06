FROM python:3.12-slim AS runtime
ARG XRAY_VERSION=26.9.30
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data APP_PORT=5000 XRAY_PORT=10000 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends nginx ca-certificates curl unzip tini && rm -rf /var/lib/apt/lists/* \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in amd64) xarch=64;; arm64) xarch=arm64-v8a;; *) echo "Unsupported architecture: $arch"; exit 1;; esac \
    && curl -fsSL "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/Xray-linux-${xarch}.zip" -o /tmp/xray.zip \
    && unzip -q /tmp/xray.zip -d /usr/local/bin/xray-dist \
    && install -m 0755 /usr/local/bin/xray-dist/xray /usr/local/bin/xray \
    && rm -rf /tmp/xray.zip /usr/local/bin/xray-dist
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x /app/start.sh && mkdir -p /app/data /run/nginx
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["/app/start.sh"]
