# Development Guide

## Development Workflow

### Daily Workflow

```bash
# 1. Pull latest changes
git pull origin main

# 2. Start services if not running
docker compose up -d

# 3. Apply any new migrations
alembic upgrade head

# 4. Start dev server
uvicorn app.main:app --reload --port 8000

# 5. Work on your feature
# 6. Run tests before committing
pytest --cov=app --cov-fail-under=80
ruff check . && ruff format --check .
mypy app/

# 7. Commit and push
git add .
git commit -m "feat(tasks): add bulk status update endpoint"
git push origin feature/bulk-task-update
```

---

## Adding a New Feature (Full Example)

### Scenario: Add a "due date reminder" email notification

#### 1. Create the migration (if DB change needed)

In this case no schema change is required since `due_date` already exists.

#### 2. Add the service method

`app/services/notification_service.py`:

```python
class NotificationService:
    async def send_due_date_reminders(self, db: AsyncSession) -> int:
        """Send reminders for tasks due within 24 hours. Returns count sent."""
        tomorrow = datetime.now(timezone.utc) + timedelta(hours=24)
        tasks = await task_repo.get_tasks_due_before(db, deadline=tomorrow, reminded=False)

        sent = 0
        for task in tasks:
            assignee = await user_repo.get_by_id(db, task.assignee_id)
            if assignee:
                await email_service.send_due_date_reminder(
                    to=assignee.email,
                    task_title=task.title,
                    due_date=task.due_date,
                )
                await task_repo.mark_reminded(db, task.id)
                sent += 1

        await db.commit()
        return sent
```

#### 3. Add the background task

`app/tasks/reminders.py`:

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job("interval", hours=1)
async def send_reminders():
    async with AsyncSessionLocal() as db:
        count = await notification_service.send_due_date_reminders(db)
        logger.info(f"Sent {count} due-date reminders")
```

#### 4. Register the scheduler in the app

```python
# app/main.py
from app.tasks.reminders import scheduler

@app.on_event("startup")
async def start_scheduler():
    scheduler.start()

@app.on_event("shutdown")
async def stop_scheduler():
    scheduler.shutdown()
```

#### 5. Write unit tests

```python
# tests/unit/test_notification_service.py
async def test_send_reminders_skips_tasks_without_assignee(db_session, task_without_assignee):
    with patch("app.services.notification_service.email_service.send_due_date_reminder") as mock_email:
        count = await notification_service.send_due_date_reminders(db_session)
    mock_email.assert_not_called()
    assert count == 0
```

---

## Database Migrations

### Create a Migration

After modifying an ORM model, generate the migration:

```bash
alembic revision --autogenerate -m "add reminded_at column to tasks"
```

Review the generated file in `alembic/versions/`. Always verify:
- The correct columns/indexes are added
- `downgrade()` properly reverses the change

### Apply Migrations

```bash
alembic upgrade head   # apply all pending
alembic upgrade +1     # apply exactly one migration
```

### Rollback

```bash
alembic downgrade -1   # revert last migration
alembic downgrade base # revert all (WARNING: destructive in production)
```

### Migration History

```bash
alembic history --verbose
alembic current
```

---

## Code Style Rules

### Imports Order

```python
# 1. Standard library
import os
from datetime import datetime, timezone
from typing import Optional

# 2. Third-party
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

# 3. Local application
from app.config import settings
from app.utils.auth import get_current_user
```

Use `ruff` to auto-sort imports: `ruff check --select I --fix .`

### Async Functions

```python
# ✅ Correct: async all the way
async def get_task(task_id: UUID, db: AsyncSession) -> Task:
    return await task_repo.get_by_id(db, task_id)

# ❌ Wrong: mixing sync and async
def get_task(task_id: UUID, db: AsyncSession) -> Task:
    return asyncio.run(task_repo.get_by_id(db, task_id))  # blocks event loop
```

### Type Annotations

```python
# ✅ Full annotations
async def create_task(
    data: TaskCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    ...

# ❌ Missing return type and parameter types
async def create_task(data, user=Depends(get_current_user), db=Depends(get_db)):
    ...
```

---

## Debugging Tips

### Enable SQL Query Logging

```python
# In app/database.py, development only:
engine = create_async_engine(
    str(settings.database_url),
    echo=settings.app_env == "development",  # logs all SQL
)
```

### Inspect Redis Cache

```bash
docker compose exec redis redis-cli
> KEYS *            # list all keys
> GET "tasks:..."   # inspect a specific key
> FLUSHDB           # clear cache (dev only)
```

### FastAPI Debug Mode

With `--reload`, FastAPI auto-restarts on code changes.
Use `logging.DEBUG` in `.env` to get verbose request/response logs:

```dotenv
LOG_LEVEL=DEBUG
```

### Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `MissingGreenlet` | Sync DB call inside async context | Use `await` everywhere |
| `DetachedInstanceError` | Accessing lazy-loaded attr after session closed | Use `selectinload()` in the query |
| `greenlet_spawn has not been called` | `expire_on_commit=True` (default) | Set `expire_on_commit=False` in session factory |
| `422 Unprocessable Entity` | Pydantic field validation failed | Inspect `detail` list in response body |

---

## Profiling Performance

```bash
# Install profiler
pip install pyinstrument

# Profile a specific endpoint
python -m pyinstrument -m uvicorn app.main:app --port 8001
# then hit the endpoint while the server runs

# Or in code:
from pyinstrument import Profiler

@router.get("/tasks")
async def list_tasks(...):
    with Profiler(async_mode="enabled") as profiler:
        result = await task_service.list_tasks(db, user, filters)
    profiler.print()
    return result
```
