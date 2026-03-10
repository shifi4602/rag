# Setup and Installation Guide

## System Requirements

- Python **3.11** or later
- Docker and Docker Compose (v2)
- 2 GB RAM minimum (4 GB recommended)
- 10 GB free disk space

---

## Step-by-Step Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-org/task-manager-api.git
cd task-manager-api
```

### 2. Set up Python virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate      # Linux / macOS
.venv\Scripts\activate         # Windows PowerShell
```

### 3. Install dependencies

```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt       # runtime
pip install -r requirements-dev.txt   # linters, test tools
```

`requirements.txt` key entries:
```
fastapi==0.111.0
uvicorn[standard]==0.30.0
sqlalchemy[asyncio]==2.0.30
asyncpg==0.29.0
alembic==1.13.1
pydantic-settings==2.2.1
redis==5.0.4
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
```

`requirements-dev.txt` key entries:
```
pytest==8.2.0
pytest-asyncio==0.23.6
pytest-cov==5.0.0
httpx==0.27.0
ruff==0.4.4
mypy==1.10.0
```

### 4. Configure environment

```bash
cp .env.example .env
```

Minimum required values for local development:

```dotenv
APP_ENV=development
APP_SECRET_KEY=dev-secret-key-change-in-production
DATABASE_URL=postgresql+asyncpg://taskuser:taskpass@localhost:5432/taskdb
REDIS_URL=redis://localhost:6379/0
ALLOWED_ORIGINS=http://localhost:3000
```

### 5. Start backing services

```bash
docker compose up -d
```

This starts:
- **PostgreSQL** on `localhost:5432`
- **Redis** on `localhost:6379`
- **pgAdmin** on `http://localhost:5050` (optional, for DB exploration)

### 6. Initialize the database

Run migrations to create all tables:

```bash
alembic upgrade head
```

Verify the current migration state:

```bash
alembic current
```

Optionally load demo data:

```bash
python scripts/seed_data.py
```

Demo credentials after seeding:
- admin@example.com / Admin1234!
- alice@example.com / Demo1234!
- bob@example.com / Demo1234!

### 7. Run the API

```bash
uvicorn app.main:app --reload --port 8000
```

Test it:

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"1.3.0","database":"connected","cache":"connected"}
```

Interactive docs: **http://localhost:8000/docs**

---

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=app --cov-report=html
open htmlcov/index.html   # view in browser

# Only unit tests
pytest tests/unit/

# Only integration tests
pytest tests/integration/

# Single file
pytest tests/integration/test_tasks.py -v

# Stop on first failure
pytest -x
```

The test suite requires a separate test database `taskdb_test`.
The `conftest.py` creates and tears it down automatically.

---

## Linting and Formatting

```bash
# Check formatting
ruff format --check .

# Apply formatting
ruff format .

# Lint
ruff check .

# Type check
mypy app/
```

CI enforces zero lint errors and zero type errors.

---

## Makefile Shortcuts

```bash
make run       # start dev server
make test      # run test suite
make lint      # ruff check + mypy
make format    # ruff format
make migrate   # alembic upgrade head
make seed      # load demo data
make clean     # remove __pycache__ and .pytest_cache
```

---

## IDE Setup

### VS Code

Recommended extensions: `ms-python.python`, `ms-python.ruff`, `tamasfe.even-better-toml`.

`.vscode/settings.json`:
```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true
  }
}
```

### PyCharm

Set the interpreter to `.venv/bin/python` and enable the Ruff plugin for auto-formatting.

---

## Troubleshooting Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `asyncpg: could not connect to server` | PostgreSQL not running | `docker compose up -d postgres` |
| `alembic: Can't locate revision` | Stale migration | `alembic stamp head` |
| `422 Unprocessable Entity` | Request body validation failed | Check the `detail` field in the response |
| `ImportError: No module named 'app'` | Wrong working directory | Run commands from project root |
| Port 8000 already in use | Another process running | `kill $(lsof -t -i:8000)` |
