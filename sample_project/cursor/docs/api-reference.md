# API Reference

Base URL: `https://api.example.com/api/v1`

All endpoints require `Authorization: Bearer <access_token>` unless noted otherwise.

---

## Authentication

### POST /auth/login

Authenticate with email and password. Returns JWT access token and refresh token.

**No authentication required.**

**Request body:**
```json
{
  "email": "user@example.com",
  "password": "MyPassword1!"
}
```

**Response 200:**
```json
{
  "success": true,
  "data": {
    "accessToken": "eyJhbGci...",
    "refreshToken": "def50200...",
    "expiresIn": 86400,
    "user": {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "email": "user@example.com",
      "fullName": "Alice Smith",
      "role": "member"
    }
  }
}
```

**Response 401** ��� invalid credentials.

---

### POST /auth/refresh

Exchange a refresh token for a new access token.

**No authentication required.**

**Request body:**
```json
{ "refreshToken": "def50200..." }
```

**Response 200:**
```json
{
  "success": true,
  "data": { "accessToken": "eyJhbGci...", "expiresIn": 86400 }
}
```

---

### POST /auth/logout

Revoke the current refresh token.

**Response 204** ��� no content.

---

## Tasks

### GET /tasks

Return a paginated list of tasks visible to the current user.

**Query parameters:**

| Parameter       | Type    | Default | Description                              |
|-----------------|---------|---------|------------------------------------------|
| page            | int     | 1       | Page number                              |
| page_size       | int     | 20      | Items per page (max 100)                 |
| filter_status   | string  | ���       | `open`, `in_progress`, `done`, `archived`|
| filter_priority | string  | ���       | `low`, `medium`, `high`, `critical`      |
| filter_project  | UUID    | ���       | Restrict to one project                  |
| q               | string  | ���       | Full-text search on title/description    |
| sort_by         | string  | created_at | Column to sort by                     |
| sort_order      | string  | desc    | `asc` or `desc`                          |

**Response 200:**
```json
{
  "success": true,
  "data": {
    "items": [ { "id": "...", "title": "...", "status": "open", "priority": "high" } ],
    "total": 42,
    "page": 1,
    "pageSize": 20,
    "hasNext": true,
    "hasPrev": false
  }
}
```

---

### POST /tasks

Create a new task.

**Request body:**
```json
{
  "title": "Design login page",
  "description": "Use Figma mockups from the design team.",
  "priority": "high",
  "dueDate": "2026-06-30T23:59:59Z",
  "projectId": "3fa85f64-...",
  "assigneeId": "7c9e6679-...",
  "tagIds": ["a3bb189e-..."]
}
```

**Response 201:**
```json
{
  "success": true,
  "data": { "id": "1e4a1b03-...", "title": "Design login page", "status": "open", ... }
}
```

---

### GET /tasks/{task_id}

Retrieve a single task by ID.

**Response 200:** Full task object.
**Response 404:** Task not found.

---

### PATCH /tasks/{task_id}

Partially update a task. Only provided fields are changed.

**Request body (all fields optional):**
```json
{
  "title": "Updated title",
  "status": "in_progress",
  "priority": "critical",
  "dueDate": "2026-07-15T00:00:00Z"
}
```

**Response 200:** Updated task object.
**Response 403:** Not authorized to modify this task.

---

### DELETE /tasks/{task_id}

Delete a task permanently.

**Response 204** ��� no content.
**Response 403** ��� only the task creator or project admin can delete.

---

## Projects

### GET /projects

Return projects the current user is a member of.

**Response 200:** Paginated list of project objects.

---

### POST /projects

Create a new project. The creator becomes the project admin.

**Request body:**
```json
{
  "name": "Website Redesign",
  "description": "Q3 2026 rebrand initiative",
  "isPublic": false
}
```

**Response 201:** New project object.

---

### POST /projects/{project_id}/members

Invite a user to a project.

**Request body:**
```json
{ "userId": "7c9e6679-...", "role": "member" }
```

**Response 201:** Updated member list.

---

## Comments

### GET /tasks/{task_id}/comments

List all comments on a task (chronological order).

**Response 200:** Array of comment objects.

---

### POST /tasks/{task_id}/comments

Add a comment to a task.

**Request body:**
```json
{ "body": "This is blocked by task #42." }
```

**Response 201:** New comment object.

---

## Users

### GET /users/me

Return the current authenticated user's profile.

**Response 200:**
```json
{
  "success": true,
  "data": {
    "id": "3fa85f64-...",
    "email": "alice@example.com",
    "fullName": "Alice Smith",
    "avatarUrl": "https://cdn.example.com/avatars/alice.jpg",
    "role": "member",
    "createdAt": "2025-01-15T10:30:00Z"
  }
}
```

---

### PATCH /users/me

Update current user's profile (name, avatar URL, password).

---

## Health Check

### GET /health

Returns API health status. No authentication required.

**Response 200:**
```json
{
  "status": "ok",
  "version": "1.3.0",
  "database":xxxxxxxxxxcted",
  "cache": "connected"
}
```
