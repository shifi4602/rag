# Core Components

## Application Factory (`app/main.py`)

The entry point creates the FastAPI app, registers routers, and wires up middleware:

```python
from fastapi import FastAPI
from app.routers import auth, tasks, projects, users, comments
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.middleware.request_id import RequestIdMiddleware
from app.utils.errors import register_exception_handlers

def create_app() -> FastAPI:
    app = FastAPI(
        title="Task Manager API",
        version="1.3.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Middleware (applied in reverse order)
    app.add_middleware(RateLimiterMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # Routers
    app.include_router(auth.router,     prefix="/api/v1/auth",     tags=["auth"])
    app.include_router(tasks.router,    prefix="/api/v1/tasks",    tags=["tasks"])
    app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
    app.include_router(users.router,    prefix="/api/v1/users",    tags=["users"])
    app.include_router(comments.router, prefix="/api/v1",          tags=["comments"])

    register_exception_handlers(app)
    return app

app = create_app()
```

---

## Database (`app/database.py`)

Async SQLAlchemy engine with a context-manager session factory:

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.config import settings

engine = create_async_engine(str(settings.database_url), pool_size=10, max_overflow=20)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

The `get_db` function is injected via `Depends(get_db)` in all routers.

---

## Authentication Utilities (`app/utils/auth.py`)

### Password Hashing

```python
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
```

### JWT Handling

```python
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone

def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.app_secret_key, algorithm="HS256")

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.app_secret_key, algorithms=["HS256"])
    except JWTError:
        raise AppError(status_code=401, code="INVALID_TOKEN", message="Token is invalid or expired.")
```

### Current User Dependency

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(token)
    user = await user_repo.get_by_id(db, UUID(payload["sub"]))
    if not user:
        raise AppError(status_code=401, code="USER_NOT_FOUND", message="User no longer exists.")
    return user
```

---

## Task Service (`app/services/task_service.py`)

The central business logic component for task management:

```python
class TaskService:
    async def create_task(self, db: AsyncSession, user: User, data: TaskCreateRequest) -> Task:
        # Authorization: user must be a project member
        await self._assert_project_member(db, user, data.project_id)

        task = Task(
            title=data.title,
            description=data.description,
            priority=data.priority,
            due_date=data.due_date,
            project_id=data.project_id,
            creator_id=user.id,
            assignee_id=data.assignee_id,
        )
        db.add(task)

        if data.tag_ids:
            tags = await tag_repo.get_by_ids(db, data.tag_ids)
            task.tags = tags

        await db.commit()
        await db.refresh(task)
        await cache.invalidate_project_tasks(data.project_id)
        return task

    async def list_tasks(
        self,
        db: AsyncSession,
        user: User,
        filters: TaskFilters,
    ) -> tuple[list[Task], int]:
        cache_key = f"tasks:{user.id}:{filters.cache_key()}"
        if cached := await cache.get(cache_key):
            return cached

        tasks, total = await task_repo.list_tasks(db, user.id, filters)
        await cache.set(cache_key, (tasks, total), ttl=60)
        return tasks, total
```

---

## Pagination Utility (`app/utils/pagination.py`)

```python
class PaginationParams:
    def __init__(self, page: int = 1, page_size: int = 20):
        if page < 1:
            raise AppError(400, "INVALID_PAGE", "Page must be >= 1.")
        if not 1 <= page_size <= 100:
            raise AppError(400, "INVALID_PAGE_SIZE", "page_size must be between 1 and 100.")
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size

def paginate_response(items, total: int, params: PaginationParams) -> dict:
    return {
        "items": items,
        "total": total,
        "page": params.page,
        "pageSize": params.page_size,
        "hasNext": params.offset + params.page_size < total,
        "hasPrev": params.page > 1,
    }
```

---

## Error Handling (`app/utils/errors.py`)

```python
class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": exc.to_dict()},
        )
```

---

## Cache Layer (`app/utils/cache.py`)

Thin async wrapper around `redis.asyncio`:

```python
class CacheService:
    def __init__(self, redis_url: str):
        self._client = redis.from_url(redis_url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        data = await self._client.get(key)
        return orjson.loads(data) if data else None

    async def set(self, key: str, value: Any, ttl: int = 60) -> None:
        await self._client.set(key, orjson.dumps(value), ex=ttl)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def invalidate_project_tasks(self, project_id: UUID) -> None:
        pattern = f"tasks:*:{project_id}:*"
        keys = await self._client.keys(pattern)
        if keys:
            await self._client.delete(*keys)

cache = CacheService(settings.redis_url)
```
