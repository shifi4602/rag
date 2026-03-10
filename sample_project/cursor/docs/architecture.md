# Architecture

## High-Level Overview

The Task Manager API follows a **layered architecture** pattern with clear boundaries
between the HTTP transport layer, business logic, and data persistence.

```
┌─────────────────────────────────────────────────────────────┐
│                     Client (Browser / App)                  │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTPS
┌───────────────────────────▼─────────────────────────────────┐
│                    Nginx (reverse proxy)                    │
│         TLS termination · static files · rate limit        │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────────┐
│              FastAPI Application (Uvicorn workers)          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Routers  │→ │ Services │→ │  Repos   │→ │  Models  │   │
│  └──────────┘  └────┬─────┘  └────┬─────┘  └──────────┘   │
│                     │             │                         │
│              ┌──────┘      ┌──────┘                         │
│              ▼             ▼                                │
│         ┌────────┐   ┌──────────┐                           │
│         │ Redis  │   │Postgres  │                           │
│         └────────┘   └──────────┘                           │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer Descriptions

### Routers (`app/routers/`)

- Thin HTTP handlers; minimal logic.
- Validate request schemas with Pydantic.
- Extract dependencies (current user, DB session, Redis).
- Call exactly one service function, then return the response schema.

### Services (`app/services/`)

- Contains all business logic.
- Orchestrates multiple repository calls when needed.
- Raises typed `AppError` exceptions; never `HTTPException`.
- Completely independent of FastAPI; easily unit-testable.

### Repositories (`app/repositories/`)

- Thin async wrappers around SQLAlchemy queries.
- Return ORM model instances or lists thereof.
- No business logic; only data access.

### Models (`app/models/`)

- SQLAlchemy ORM mapped classes.
- Follow the DB conventions from project-rules.

### Schemas (`app/schemas/`)

- Pydantic v2 models for request bodies and response payloads.
- Strict separation: `XxxRequest`, `XxxResponse`, `XxxUpdate`.

---

## Domain Model

```
User ────< UserProject ────> Project ────< Task
  │                                          │
  └────< AuthToken                           ├────< TaskTag >──── Tag
                                             ├────< Comment
                                             └──── Assignee (User FK)
```

### Core Entities

| Entity      | Description                                            |
|-------------|--------------------------------------------------------|
| User        | Registered account; owns projects; can be assigned tasks |
| Project     | Container for tasks; has members with roles            |
| Task        | A work item: title, description, priority, due date    |
| Tag         | Reusable label attached to tasks                       |
| Comment     | Thread entry on a task                                 |
| AuthToken   | Refresh token record (for revocation)                  |

---

## Authentication and Authorization

### Token Flow

```
1. POST /auth/login  → issue access_token (JWT, 24h) + refresh_token (opaque, 30d)
2. Every request     → Bearer <access_token> in Authorization header
3. Token expiry      → POST /auth/refresh with refresh_token cookie
4. Logout            → DELETE /auth/logout revokes refresh_token in DB
```

### Role System

| Role    | Scope   | Permissions                                   |
|---------|---------|-----------------------------------------------|
| admin   | Global  | Manage all users, projects, and system config |
| member  | Project | Create/edit tasks in their projects           |
| viewer  | Project | Read-only access to project tasks             |

Permission checks happen in the service layer, not in routers.

---

## Caching Strategy

Redis is used for three purposes:

1. **Session store** – refresh token lookup (key: `refresh:<token_id>`, TTL 30 days)
2. **Response cache** – frequently-read project/task lists (TTL 60 seconds)
3. **Rate limiter** – sliding window counter per IP address (TTL 60 seconds)

Cache invalidation follows "write-through": on every mutation, the affected cache
key(s) are deleted immediately.

---

## Async Architecture

All I/O is async end-to-end:

- `asyncpg` for PostgreSQL
- `aioredis` for Redis
- `httpx` for outgoing HTTP calls

The application runs with `uvicorn --workers 4` behind Nginx.
Do **not** use `asyncio.run()` or synchronous blocking calls inside route handlers.

---

## Configuration

All settings are read from environment variables via `pydantic-settings`:

```python
class Settings(BaseSettings):
    app_env: str = "development"
    database_url: PostgresDsn
    redis_url: RedisDsn
    app_secret_key: str
    access_token_expire_minutes: int = 1440
    refresh_token_expire_days: int = 30
    allowed_origins: list[str] = []

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
```

---

## Observability

| Signal  | Tool              | Notes                              |
|---------|-------------------|------------------------------------|
| Logs    | structlog (JSON)  | Request ID injected via middleware |
| Metrics | Prometheus        | `/metrics` endpoint (internal only)|
| Traces  | OpenTelemetry     | Exported to Jaeger in staging/prod |
| Errors  | Sentry            | Enabled in staging/prod only       |
