# Cloud deployment (production)

## What you get

- TLS (Let's Encrypt) via Caddy
- Only ports 80/443 exposed
- Postgres/Redis/MinIO are private inside the Docker network
- Persistent volumes for DB/storage/app state

## Prerequisites

- A VPS (Ubuntu recommended)
- DNS A-record for your domain pointing to the VPS
- Docker + Docker Compose plugin installed

## Files

- `docker-compose.prod.yml`
- `Caddyfile`
- `backend/.env`

## Required environment

On the server, create `.env` next to `docker-compose.prod.yml` (root of repo) with:

```bash
CORELMS_DOMAIN=your-domain.com
ACME_EMAIL=admin@your-domain.com
NEXT_PUBLIC_API_BASE_URL=https://your-domain.com

POSTGRES_DB=corelms
POSTGRES_USER=corelms
POSTGRES_PASSWORD=CHANGE_ME_STRONG

MINIO_ROOT_USER=minio
MINIO_ROOT_PASSWORD=CHANGE_ME_STRONG
```

And create `backend/.env` based on `backend/.env.example`.

Production minimum:

```bash
APP_ENV=production
ALLOW_PUBLIC_REGISTER=false
JWT_SECRET_KEY=CHANGE_ME_STRONG_LONG_RANDOM
CORS_ALLOW_ORIGINS=https://your-domain.com

S3_BUCKET=sdlp-content
S3_ACCESS_KEY_ID=CHANGE_ME_STRONG
S3_SECRET_ACCESS_KEY=CHANGE_ME_STRONG

HF_ROUTER_ENABLED=false
OLLAMA_ENABLED=false
```

## Start

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## Smoke checks

- Open `https://your-domain.com`
- Backend readiness (through Next.js proxy):

```bash
curl -fsS https://your-domain.com/api/backend/health/ready
```

Or use the provided script:

```bash
NEXT_PUBLIC_API_BASE_URL=https://your-domain.com ./scripts/smoke-prod.sh
```

This project is designed to keep the backend private inside the Docker network.

## Backups

### Postgres (logical dump)

```bash
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U corelms -d corelms -Fc > backup.dump
```

Or use the provided script (recommended):

```bash
./scripts/backup-prod.sh
```

This creates `backups/<timestamp>/postgres.dump` and also archives MinIO volume.

### Restore

```bash
./scripts/restore-prod.sh backups/<timestamp>
```

IMPORTANT: this will overwrite Postgres DB and MinIO volume.

## Logs

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f --tail=200
docker compose -f docker-compose.prod.yml logs -f --tail=200 backend
docker compose -f docker-compose.prod.yml logs -f --tail=200 worker
```

Store backups off-server.

### MinIO

- Content is stored in Docker volume `minio_data`.
- Recommended: set up external S3 for production or replicate using `mc mirror`.
