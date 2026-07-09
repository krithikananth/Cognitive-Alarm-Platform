# 📡 API Documentation

## Intelligent Cognitive Alarm Platform (ICAP)

---

## 1. Overview

| Property         | Value                                       |
| ---------------- | ------------------------------------------- |
| **Base URL**     | `http://localhost:8000/api/v1`               |
| **API Version**  | `v1`                                        |
| **Format**       | JSON                                        |
| **Auth Method**  | Bearer Token (JWT)                          |
| **Docs (Swagger)** | `http://localhost:8000/docs`              |
| **Docs (ReDoc)** | `http://localhost:8000/redoc`               |
| **OpenAPI Spec** | `http://localhost:8000/openapi.json`        |

---

## 2. Authentication

ICAP uses **JSON Web Tokens (JWT)** for authentication. After logging in or registering, the API returns an access token and a refresh token.

### How It Works

1. **Register** or **Login** to receive tokens
2. Include the access token in the `Authorization` header for protected endpoints
3. When the access token expires, use the refresh token to obtain a new one

### Authorization Header Format

```
Authorization: Bearer <access_token>
```

### Token Lifetimes

| Token          | Lifetime   | Purpose                |
| -------------- | ---------- | ---------------------- |
| Access Token   | 30 minutes | API request auth       |
| Refresh Token  | 7 days     | Renewing access tokens |

---

## 3. Endpoints

### 3.1 Health Check

#### `GET /`

Root endpoint — returns a welcome message.

**Auth Required:** No

**Response:**

```json
{
  "message": "Welcome to the Intelligent Cognitive Alarm Platform API",
  "version": "1.0.0",
  "docs": "/docs"
}
```

---

#### `GET /health`

Health check endpoint for monitoring.

**Auth Required:** No

**Response:**

```json
{
  "status": "healthy",
  "timestamp": "2026-07-01T12:00:00Z"
}
```

---

### 3.2 Authentication

#### `POST /api/v1/auth/register`

Register a new user account.

**Auth Required:** No

**Request Body:**

```json
{
  "email": "user@example.com",
  "username": "johndoe",
  "password": "SecureP@ss123"
}
```

**Validation Rules:**

| Field      | Rules                                           |
| ---------- | ----------------------------------------------- |
| `email`    | Valid email format, max 255 chars, unique        |
| `username` | 3-100 chars, alphanumeric + underscores, unique  |
| `password` | Min 8 chars, at least 1 uppercase, 1 digit       |

**Response — `201 Created`:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "username": "johndoe",
  "role": "user",
  "is_active": true,
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Error — `409 Conflict`:**

```json
{
  "detail": "A user with this email already exists"
}
```

---

#### `POST /api/v1/auth/login`

Authenticate and receive JWT tokens.

**Auth Required:** No

**Request Body (JSON):**

```json
{
  "email": "user@example.com",
  "password": "SecureP@ss123"
}
```

**Alternative — Form Data (`application/x-www-form-urlencoded`):**

```
username=user@example.com&password=SecureP@ss123
```

**Response — `200 OK`:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Error — `401 Unauthorized`:**

```json
{
  "detail": "Invalid email or password"
}
```

---

#### `POST /api/v1/auth/refresh`

Refresh an expired access token using a valid refresh token.

**Auth Required:** No (uses refresh token in body)

**Request Body:**

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response — `200 OK`:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Error — `401 Unauthorized`:**

```json
{
  "detail": "Invalid or expired refresh token"
}
```

---

#### `POST /api/v1/auth/logout`

Invalidate the current session.

**Auth Required:** 🔑 Yes

**Headers:**

```
Authorization: Bearer <access_token>
```

**Response — `200 OK`:**

```json
{
  "message": "Successfully logged out"
}
```

---

### 3.3 User Management

#### `GET /api/v1/users/me`

Get the currently authenticated user's information.

**Auth Required:** 🔑 Yes

**Response — `200 OK`:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "username": "johndoe",
  "role": "user",
  "is_active": true,
  "is_verified": false,
  "created_at": "2026-07-01T12:00:00Z",
  "updated_at": "2026-07-01T12:00:00Z"
}
```

---

#### `PUT /api/v1/users/me`

Update the currently authenticated user's account information.

**Auth Required:** 🔑 Yes

**Request Body:**

```json
{
  "username": "john_doe_updated",
  "email": "newemail@example.com"
}
```

**Response — `200 OK`:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "newemail@example.com",
  "username": "john_doe_updated",
  "role": "user",
  "is_active": true,
  "is_verified": false,
  "created_at": "2026-07-01T12:00:00Z",
  "updated_at": "2026-07-01T12:30:00Z"
}
```

---

#### `GET /api/v1/users`

List all users. **Admin only.**

**Auth Required:** 🔑 Admin

**Query Parameters:**

| Parameter | Type    | Default | Description               |
| --------- | ------- | ------- | ------------------------- |
| `skip`    | integer | `0`     | Number of records to skip |
| `limit`   | integer | `20`    | Max records to return     |
| `search`  | string  | —       | Search by email/username  |

**Response — `200 OK`:**

```json
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "email": "user@example.com",
      "username": "johndoe",
      "role": "user",
      "is_active": true,
      "created_at": "2026-07-01T12:00:00Z"
    }
  ],
  "total": 42,
  "skip": 0,
  "limit": 20
}
```

---

#### `GET /api/v1/users/{user_id}`

Get a specific user by ID. **Admin only.**

**Auth Required:** 🔑 Admin

**Path Parameters:**

| Parameter | Type | Description        |
| --------- | ---- | ------------------ |
| `user_id` | UUID | Target user's UUID |

**Response — `200 OK`:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "username": "johndoe",
  "role": "user",
  "is_active": true,
  "is_verified": false,
  "created_at": "2026-07-01T12:00:00Z",
  "updated_at": "2026-07-01T12:00:00Z"
}
```

**Error — `404 Not Found`:**

```json
{
  "detail": "User not found"
}
```

---

#### `DELETE /api/v1/users/{user_id}`

Delete a user (soft delete). **Admin only.**

**Auth Required:** 🔑 Admin

**Path Parameters:**

| Parameter | Type | Description        |
| --------- | ---- | ------------------ |
| `user_id` | UUID | Target user's UUID |

**Response — `200 OK`:**

```json
{
  "message": "User successfully deleted",
  "user_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

---

### 3.4 Profile

#### `GET /api/v1/profile`

Get the authenticated user's profile.

**Auth Required:** 🔑 Yes

**Response — `200 OK`:**

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "display_name": "John Doe",
  "avatar_url": null,
  "timezone": "America/New_York",
  "preferences": {
    "theme": "dark",
    "notifications_enabled": true,
    "challenge_types": ["math", "memory"]
  },
  "wake_up_goal": "06:30",
  "cognitive_level": 5,
  "created_at": "2026-07-01T12:00:00Z",
  "updated_at": "2026-07-01T12:00:00Z"
}
```

---

#### `PUT /api/v1/profile`

Update the authenticated user's profile.

**Auth Required:** 🔑 Yes

**Request Body:**

```json
{
  "display_name": "John D.",
  "timezone": "Asia/Kolkata",
  "wake_up_goal": "05:30",
  "cognitive_level": 7
}
```

**Response — `200 OK`:**

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "display_name": "John D.",
  "avatar_url": null,
  "timezone": "Asia/Kolkata",
  "preferences": {
    "theme": "dark",
    "notifications_enabled": true,
    "challenge_types": ["math", "memory"]
  },
  "wake_up_goal": "05:30",
  "cognitive_level": 7,
  "created_at": "2026-07-01T12:00:00Z",
  "updated_at": "2026-07-01T12:30:00Z"
}
```

---

#### `PATCH /api/v1/profile/preferences`

Update only the user's preferences object (partial update).

**Auth Required:** 🔑 Yes

**Request Body:**

```json
{
  "theme": "light",
  "notifications_enabled": false,
  "challenge_types": ["math", "pattern", "word"]
}
```

**Response — `200 OK`:**

```json
{
  "preferences": {
    "theme": "light",
    "notifications_enabled": false,
    "challenge_types": ["math", "pattern", "word"]
  },
  "updated_at": "2026-07-01T12:45:00Z"
}
```

---

### 3.5 Alarms *(Milestone 2 — Planned)*

#### `POST /api/v1/alarms`

Create a new alarm.

**Auth Required:** 🔑 Yes

**Request Body:**

```json
{
  "alarm_time": "06:30",
  "label": "Morning Workout",
  "repeat_days": [1, 2, 3, 4, 5],
  "snooze_limit": 2,
  "snooze_interval": 5,
  "sound": "gentle_rise",
  "require_challenge": true,
  "challenge_type": "math",
  "challenge_difficulty": 5
}
```

**Response — `201 Created`:**

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440000",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "alarm_time": "06:30:00",
  "label": "Morning Workout",
  "repeat_days": [1, 2, 3, 4, 5],
  "is_active": true,
  "snooze_limit": 2,
  "snooze_interval": 5,
  "sound": "gentle_rise",
  "require_challenge": true,
  "challenge_type": "math",
  "challenge_difficulty": 5,
  "created_at": "2026-07-01T12:00:00Z",
  "updated_at": "2026-07-01T12:00:00Z"
}
```

---

#### `GET /api/v1/alarms`

List all alarms for the authenticated user.

**Auth Required:** 🔑 Yes

**Query Parameters:**

| Parameter   | Type    | Default | Description               |
| ----------- | ------- | ------- | ------------------------- |
| `is_active` | boolean | —       | Filter by active status   |
| `skip`      | integer | `0`     | Pagination offset         |
| `limit`     | integer | `20`    | Max records to return     |

**Response — `200 OK`:**

```json
{
  "items": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440000",
      "alarm_time": "06:30:00",
      "label": "Morning Workout",
      "is_active": true,
      "require_challenge": true,
      "repeat_days": [1, 2, 3, 4, 5]
    }
  ],
  "total": 3,
  "skip": 0,
  "limit": 20
}
```

---

#### `GET /api/v1/alarms/{alarm_id}`

Get a specific alarm.

**Auth Required:** 🔑 Yes

---

#### `PUT /api/v1/alarms/{alarm_id}`

Update an alarm.

**Auth Required:** 🔑 Yes

---

#### `DELETE /api/v1/alarms/{alarm_id}`

Delete an alarm.

**Auth Required:** 🔑 Yes

**Response — `200 OK`:**

```json
{
  "message": "Alarm successfully deleted",
  "alarm_id": "770e8400-e29b-41d4-a716-446655440000"
}
```

---

## 4. Error Response Format

All error responses follow a consistent format:

### Standard Error

```json
{
  "detail": "Human-readable error message"
}
```

### Validation Error (422)

```json
{
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    },
    {
      "loc": ["body", "password"],
      "msg": "ensure this value has at least 8 characters",
      "type": "value_error.any_str.min_length"
    }
  ]
}
```

### HTTP Status Codes

| Code  | Meaning                | When Used                                    |
| ----- | ---------------------- | -------------------------------------------- |
| `200` | OK                     | Successful GET, PUT, PATCH, DELETE            |
| `201` | Created                | Successful POST (resource created)            |
| `204` | No Content             | Successful operation with no response body    |
| `400` | Bad Request            | Malformed request body                        |
| `401` | Unauthorized           | Missing or invalid authentication token       |
| `403` | Forbidden              | Insufficient permissions                      |
| `404` | Not Found              | Resource does not exist                       |
| `409` | Conflict               | Duplicate resource (email, username)           |
| `422` | Unprocessable Entity   | Validation error in request body              |
| `429` | Too Many Requests      | Rate limit exceeded                           |
| `500` | Internal Server Error  | Unexpected server error                       |

---

## 5. Pagination

All list endpoints support pagination using `skip` and `limit` query parameters.

### Request

```
GET /api/v1/users?skip=20&limit=10
```

### Response Format

```json
{
  "items": [...],
  "total": 150,
  "skip": 20,
  "limit": 10
}
```

### Defaults

| Parameter | Default | Min | Max  |
| --------- | ------- | --- | ---- |
| `skip`    | `0`     | `0` | —    |
| `limit`   | `20`    | `1` | `100`|

---

## 6. Rate Limiting

To protect the API from abuse, rate limits are enforced per IP address and per authenticated user.

| Scope           | Limit              | Window    |
| --------------- | ------------------ | --------- |
| Anonymous       | 30 requests        | 1 minute  |
| Authenticated   | 100 requests       | 1 minute  |
| Auth endpoints  | 10 requests        | 1 minute  |

### Rate Limit Headers

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1719847860
```

### Rate Limit Exceeded — `429 Too Many Requests`

```json
{
  "detail": "Rate limit exceeded. Try again in 45 seconds.",
  "retry_after": 45
}
```

---

## 7. CORS Configuration

The API supports Cross-Origin Resource Sharing (CORS) with the following default configuration:

| Setting            | Value                        |
| ------------------ | ---------------------------- |
| Allowed Origins    | `http://localhost:3000`      |
| Allowed Methods    | `GET, POST, PUT, PATCH, DELETE, OPTIONS` |
| Allowed Headers    | `Authorization, Content-Type` |
| Allow Credentials  | `true`                       |
| Max Age            | `600` seconds                |

---

## 8. Versioning

The API uses **URL-based versioning**:

```
/api/v1/...    ← Current version
/api/v2/...    ← Future version (when needed)
```

When a new version is introduced:
- The previous version will be maintained for at least **6 months**
- Deprecation notices will be communicated via response headers
- Migration guides will be provided in the documentation
