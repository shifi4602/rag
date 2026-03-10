# Setup Guide

## Prerequisites

Before you start, make sure the following tools are installed on your machine:

| Tool            | Minimum version | Install link                    |
|-----------------|-----------------|---------------------------------|
| Python          | 3.11            | https://www.python.org/downloads |
| Docker          | 24.0            | https://docs.docker.com/get-docker |
| Docker Compose  | 2.20            | Included with Docker Desktop     |
| Git             | 2.40            | https://git-scm.com             |
| make            | 4.x             | Pre-installed on macOS / Linux   |

---

## 1. Clone the Repository

```bash
git clone https://github.com/your-org/task-manager-api.git
cd task-manager-api
```

---

## 2. Create a Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows
```

---

## 3. Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt        # production dependencies
pip install -r requirements-dev.txt    # dev/test dependencies
```

### Key packages

| Package            | Purpose                       |
|--------------------|-------------------------------|
| `fastapi`          | Web framework                 |
| `uvicorn[standard]`| ASGI server                   |
| `sqlalchemy[asyncio]`| ORM                         |
| `asyncpg`          | Async PostgreSQL driver       |
| `alembic`          | Database migrations           |
| `pydantic-settings`| Configuration management      |
| `redis`            | Redis client                  |
| `python-jose[cryptography]` | JWT handling         |
| `passlib[bcrypt]`  | Password hashing              |

---

## 4. Configure Environment Variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
# Application
APP_ENV=development
APP_SECRET_KEY=change-me-to-a-random-64-char-string
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173

# PostgreSQL
DATABASE_URL=postgresql+asyncpg://taskuser:taskpass@localhost:5432/taskdb

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
ACCESS_TOKEN_EXPIRE_MINUTES=1440
REFRESH_TOKEN_EXPIRE_DAYS=30

# Email (optional for local dev)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
```

---

## 5. Start Infrastructure Services

Use Docker Compose to spin up PostgreSQL and Redis locally:

```bash
docker compose up -d postgres redis
```

Verify they are running:

```bash
docker compose ps
```

Expected output:
```
NAME               STATUS
postgres           running
redis              running
```

---

## 6. Run Database Migrations

```bash
alembic upgrade head
```

To create a new migration after changing models:

```bash
alembic revision --autogenerate -m "add task tags table"
alembic upgrade head
```

---

## 7. Seed Development Data (Optional)

```bash
python scripts/seed_data.py
```

This creates:
- 3 demo users (admin@example.com / user1@example.com / user2@example.com)
- 10 sample projects
- 50 sample tasks with various states

Default password for all seeded users: `Demo1234!`

---

## 8. Start the Development Server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now available at:

- **API Base URL:** http://localhost:8000/api/v1
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **OpenAPI JSON:** http://localhost:8000/openapi.json

---

## 9. Verify the Installation

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "version": "1.3.0",
  "database": "connected",
  "cache": "connected"
}
```

---

## Troubleshooting

### "Address already in use" on port 8000

```bash
lsof -i :8000          # find the PID
kill -9 <PID>
```

### Database connection refused

Make sure the Docker container is running:

```bash
docker compose up -d postgres
docker compose logs postgres
```

### Alembic "target database is not up to date"

```bash
alembic stamp head   # mark current state
alembic upgrade head # apply missing migrations
```

### Import errors after pulling new code

```bash
pip install -r requirements.txt --upgrade
```
