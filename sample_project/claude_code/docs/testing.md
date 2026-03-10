# Testing Guide

## Overview

The project uses **pytest** with **pytest-asyncio** for async test support and **httpx** for HTTP-level integration tests.
Tests live under `tests/` and are split into two categories:

| Category    | Location              | Scope                          |
|-------------|-----------------------|--------------------------------|
| Unit        | `tests/unit/`         | Pure logic, no I/O             |
| Integration | `tests/integration/`  | Full HTTP stack with test DB   |

---

## Running Tests

```bash
# Run everything
pytest

# Verbose output
pytest -v

# Run a specific file
pytest tests/integration/test_tasks.py

# Run a specific test
pytest tests/integration/test_tasks.py::test_create_task_success -v

# Stop on first failure
pytest -x

# Run only tests matching a keyword
pytest -k "task and not delete"

# Coverage report in terminal
pytest --cov=app --cov-report=term-missing

# HTML coverage report
pytest --cov=app --cov-report=html
open htmlcov/index.html
```

---

## Test Configuration

`pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
```

---

## Fixtures (`tests/conftest.py`)

### Database Session

```python
@pytest.fixture(scope="session")
async def engine():
    """Create a test database engine (separate DB from development)."""
    test_engine = create_async_engine(settings.test_database_url)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield test_engine
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()

@pytest.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional DB session that rolls back after each test."""
    async with AsyncSession(engine) as session:
        async with session.begin():
            yield session
            await session.rollback()
```

### HTTP Client

```python
@pytest.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client with the app and test DB injected."""
    app.dependency_overrides[get_db] = lambda: db_session
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
```

### Auth Helpers

```python
@pytest.fixture
async def test_user(db_session) -> User:
    user = User(email="test@example.com", hashed_password=hash_password("Test1234!"), full_name="Test User")
    db_session.add(user)
    await db_session.flush()
    return user

@pytest.fixture
async def auth_headers(test_user) -> dict:
    token = create_access_token(str(test_user.id))
    return {"Authorization": f"Bearer {token}"}
```

---

## Writing Unit Tests

Unit tests live in `tests/unit/` and test service functions in isolation, mocking all I/O:

```python
# tests/unit/test_task_service.py
import pytest
from unittest.mock import AsyncMock, patch
from app.services.task_service import TaskService
from app.utils.errors import AppError

@pytest.fixture
def service() -> TaskService:
    return TaskService()

async def test_create_task_requires_project_membership(service, test_user):
    """Users must be project members to create tasks."""
    with patch("app.services.task_service.project_repo.get_member_role", return_value=None):
        with pytest.raises(AppError) as exc_info:
            await service.create_task(
                db=AsyncMock(),
                user=test_user,
                data=TaskCreateRequest(title="Test", project_id=uuid4()),
            )
    assert exc_info.value.code == "NOT_PROJECT_MEMBER"
    assert exc_info.value.status_code == 403
```

---

## Writing Integration Tests

Integration tests exercise the full HTTP stack:

```python
# tests/integration/test_tasks.py
import pytest
from httpx import AsyncClient

async def test_create_task_success(client: AsyncClient, auth_headers: dict, test_project):
    response = await client.post(
        "/api/v1/tasks",
        json={
            "title": "Write unit tests",
            "priority": "high",
            "projectId": str(test_project.id),
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["title"] == "Write unit tests"
    assert data["data"]["status"] == "open"

async def test_create_task_unauthenticated(client: AsyncClient, test_project):
    response = await client.post(
        "/api/v1/tasks",
        json={"title": "Unauthenticated task", "projectId": str(test_project.id)},
    )
    assert response.status_code == 401

async def test_list_tasks_pagination(client: AsyncClient, auth_headers: dict, many_tasks):
    response = await client.get(
        "/api/v1/tasks?page=1&page_size=5",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["items"]) == 5
    assert data["hasNext"] is True
    assert data["hasPrev"] is False
```

---

## Testing Authentication

```python
async def test_login_success(client: AsyncClient, test_user):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "Test1234!"},
    )
    assert response.status_code == 200
    assert "accessToken" in response.json()["data"]
    assert "refreshToken" in response.json()["data"]

async def test_login_wrong_password(client: AsyncClient, test_user):
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "WrongPassword"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
```

---

## Mocking External Services

Always mock external calls (email, S3, Sentry) in tests:

```python
@pytest.fixture(autouse=True)
def mock_email(monkeypatch):
    monkeypatch.setattr("app.utils.email.send_email", AsyncMock())

@pytest.fixture(autouse=True)
def mock_cache(monkeypatch):
    monkeypatch.setattr("app.utils.cache.cache.get", AsyncMock(return_value=None))
    monkeypatch.setattr("app.utils.cache.cache.set", AsyncMock())
    monkeypatch.setattr("app.utils.cache.cache.delete", AsyncMock())
```

---

## Coverage Requirements

CI fails if coverage drops below **80%**:

```bash
pytest --cov=app --cov-fail-under=80
```

To see which lines are missing coverage:

```bash
pytest --cov=app --cov-report=term-missing 2>&1 | grep -E "TOTAL|MISS"
```
