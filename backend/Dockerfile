FROM python:3.11-slim-bookworm AS builder

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim-bookworm AS runtime_base

WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ca-certificates \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app

COPY --from=builder /install /usr/local
COPY . .

RUN chmod +x /app/scripts/entrypoint.sh \
    && mkdir -p /data \
    && chown -R app:app /app /data

USER app

# Default to API mode, but can be overridden for worker
ENTRYPOINT ["/app/scripts/entrypoint.sh"]


# Only the media worker needs the Office renderer and its fonts.
FROM runtime_base AS media
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer libreoffice-impress fonts-dejavu-core fonts-liberation \
    fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*
USER app

FROM runtime_base AS runtime
