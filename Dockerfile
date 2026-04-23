FROM python:3.11-slim AS base

# System deps for cryptography, numpy
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Timezone
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Install Python deps first (cache-friendly)
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir -e .

# Persistent data directories
RUN mkdir -p /data/state /data/logs

# Default env overrides for Docker
ENV STATE_DIR=/data/state \
    LOG_DIR=/data/logs \
    HOME=/data

EXPOSE 8080

# Graceful shutdown
STOPSIGNAL SIGTERM

# Default: V2 web console
CMD ["python", "-m", "auto_coin.web", "--host", "0.0.0.0", "--port", "8080"]
