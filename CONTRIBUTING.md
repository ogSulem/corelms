# Contributing

Thanks for your interest in improving this project.

> Note: This repository uses a **proprietary license**. Contributions may require a separate agreement.

## Development setup

- Backend: FastAPI + SQLAlchemy + Alembic
- Frontend: Next.js + TypeScript

### Local run

Use Docker Compose (recommended):

```bash
docker compose up --build
```

### Tests

```bash
python -m pytest -q
```

## Pull Requests

- Keep changes small and focused
- Add/adjust tests where applicable
- Avoid introducing new dependencies unless necessary

## Code style

- Prefer explicit, readable code over cleverness
- Keep security-sensitive behavior explicit (RBAC, audit logging, secrets)
