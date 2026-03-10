# Deployment Guide

## Overview

The Task Manager API is deployed as Docker containers on a Linux VM.
The CI/CD pipeline (GitHub Actions) builds, tests, and deploys on every push to `main`.

---

## Production Stack

```
Internet → Cloudflare CDN → Nginx (proxy) → Uvicorn (4 workers)
                                          → PostgreSQL (managed)
                                          → Redis (managed)
```

---

## Docker Setup

### Build the Image

```bash
docker build -t task-manager-api:latest .
```

### docker-compose.prod.yml

```yaml
version: "3.9"
services:
  api:
    image: task-manager-api:latest
    restart: always
    env_file: .env.prod
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  postgres:
    image: postgres:15-alpine
    restart: always
    environment:
      POSTGRES_DB: taskdb
      POSTGRES_USER: taskuser
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    restart: always
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

---

## Nginx Configuration

`/etc/nginx/sites-available/task-manager-api`:

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }

    # Rate limiting zone (defined in nginx.conf)
    limit_req zone=api burst=20 nodelay;
}

server {
    listen 80;
    server_name api.example.com;
    return 301 https://$host$request_uri;
}
```

---

## CI/CD Pipeline (GitHub Actions)

`.github/workflows/deploy.yml`:

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements-dev.txt
      - run: pytest --cov=app --cov-fail-under=80

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build and push image
        run: |
          docker build -t task-manager-api:${{ github.sha }} .
          docker tag task-manager-api:${{ github.sha }} task-manager-api:latest
      - name: Deploy to server
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: deploy
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd /opt/task-manager-api
            docker compose -f docker-compose.prod.yml pull
            docker compose -f docker-compose.prod.yml up -d --force-recreate api
            docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

---

## Environment Variables (Production)

Store these in `/opt/task-manager-api/.env.prod` on the server (not in git):

```dotenv
APP_ENV=production
APP_SECRET_KEY=<64-char-random-string>
DATABASE_URL=postgresql+asyncpg://taskuser:<pw>@localhost:5432/taskdb
REDIS_URL=redis://:${REDIS_PASSWORD}@localhost:6379/0
ALLOWED_ORIGINS=https://app.example.com
ACCESS_TOKEN_EXPIRE_MINUTES=1440
REFRESH_TOKEN_EXPIRE_DAYS=30
SENTRY_DSN=https://xxxx@o0.ingest.sentry.io/0
```

---

## Database Backups

Automated daily backups via cron:

```cron
0 2 * * * /opt/scripts/backup-postgres.sh >> /var/log/db-backup.log 2>&1
```

`backup-postgres.sh`:

```bash
#!/bin/bash
DATE=$(date +%Y%m%d)
docker exec postgres pg_dump -U taskuser taskdb | gzip > /backups/taskdb-$DATE.sql.gz
# Keep last 30 days
find /backups -name "taskdb-*.sql.gz" -mtime +30 -delete
```

---

## Rollback Procedure

```bash
# List recent images
docker images task-manager-api --format "{{.Tag}}\t{{.CreatedAt}}"

# Roll back to a specific release
docker compose -f docker-compose.prod.yml up -d --force-recreate \
  --no-deps api \
  IMAGE_TAG=<previous-sha>

# If DB migration needs rollback
docker compose exec api alembic downgrade -1
```

---

## Monitoring and Alerts

| Signal           | Tool       | Alert threshold                  |
|------------------|------------|----------------------------------|
| Error rate       | Sentry     | > 1% of requests in 5 min        |
| p95 latency      | Prometheus | > 500 ms                         |
| CPU usage        | Prometheus | > 80% for 10 min                 |
| Disk usage       | Node Exp.  | > 85%                            |
| DB connections   | Prometheus | > 80% of pool size               |
| Failed logins    | Auth logs  | > 20 failures / minute / IP      |
