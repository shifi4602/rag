# Task Manager API — Claude Code Project Memory

## Project Overview

This is a **FastAPI REST API** for managing tasks, projects, and users.
Technology stack: Python 3.11 · FastAPI · PostgreSQL · Redis · Docker.

## Critical Commands

```bash
# Development server (auto-reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run all tests
pytest

# Run tests with coverage report
pytest --cov=app --cov-report=term-missing

# Apply database migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "describe change here"

# Start services (PostgreSQL + Redis)
docker compose up -d postgres redis

# Stop all services
docker compose down

# Format code
ruff format .

# Lint code
ruff check .

# Type check
mypy app/
```

## Architecture

Layered architecture: **Router → Service → Repository → Model**

- `app/routers/` — HTTP handlers (thin, no business logic)
- `app/services/` — Business rules and orchestration
- `app/repositories/` — Database access (SQLAlchemy async)
- `app/models/` — ORM table definitions
- `app/schemas/` — Pydantic v2 request/response schemas
- `app/utils/` — Auth helpers, pagination, error types
- `tests/` — Unit tests (`tests/unit/`) and integration tests (`tests/integration/`)

## Key Design Decisions

1. **Async everywhere** — Use `asyncpg` and `aioredis`; never block the event loop.
2. **Services raise `AppError`** — Routers convert these to HTTP responses via a centralized exception handler.
3. **UUID primary keys** — All entities use `gen_random_uuid()` as the default PK.
4. **No raw SQL** — Always use parameterized SQLAlchemy queries.
5. **Redis for caching** — Cache TTL = 60 s for list endpoints; invalidate on write.
6. **JWT + refresh tokens** — Access token 24 h, refresh token 30 days (stored in DB for revocation).

## Active Migrations

Most recent migration: `20260228_add_task_comments_table`

To verify current DB state:
```bash
alembic current
```

## Environment Variables

Copy `.env.example` to `.env` before running locally.  
Required variables:

```
DATABASE_URL
REDIS_URL
APP_SECRET_KEY
ALLOWED_ORIGINS
```

Optional (leave empty for local dev):
```
SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD
SENTRY_DSN
```

## Test Setup

Test DB is a separate PostgreSQL database: `taskdb_test`.
Fixtures defined in `tests/conftest.py`:
- `db_session` — async session scoped to each test function
- `client` — async `httpx.AsyncClient` with the full app
- `auth_headers` — valid JWT headers for a test user

## Common Patterns

### Create a new endpoint
1. Add route function in `app/routers/<resource>.py`
2. Add/extend Pydantic schema in `app/schemas/<resource>.py`
3. Implement logic in `app/services/<resource>_service.py`
4. Add DB query in `app/repositories/<resource>_repo.py`
5. Write integration test in `tests/integration/test_<resource>.py`

### Handle a new business rule error
```python
# In services/
raise AppError(status_code=409, code="DUPLICATE_TASK_TITLE",
               message="A task with that title already exists in this project.")
```

### Add a database index
```python
# In models/
__table_args__ = (
    Index("ix_tasks_project_id_status", "project_id", "status"),
)
```
