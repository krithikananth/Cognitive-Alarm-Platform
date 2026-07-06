# Authentication Flow Documentation

## Intelligent Cognitive Alarm Platform — Authentication & Authorization

---

## 1. Overview

The platform uses a **stateless JWT-based authentication** system with support for:
- **Email/Password** registration and login
- **OAuth2** social login (Google, GitHub)
- **Token Refresh** for seamless session continuity
- **Password Reset** via email tokens
- **Token Blacklisting** via Redis (optional)
- **Role-Based Access Control (RBAC)** with three tiers

---

## 2. Authentication Endpoints

### 2.1 Registration
```
POST /api/v1/auth/register
```
**Request Body:**
```json
{
  "email": "user@example.com",
  "username": "johndoe",
  "password": "StrongPass1",
  "full_name": "John Doe",
  "timezone": "Asia/Kolkata"
}
```
**Response (201):**
```json
{
  "access_token": "eyJhbG...",
  "refresh_token": "eyJhbG...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "uuid-string",
    "email": "user@example.com",
    "username": "johndoe",
    "role": "user",
    "is_active": true,
    "is_verified": false
  }
}
```

**Validation Rules:**
- Email: Valid format, unique
- Username: 3-100 chars, unique
- Password: 8-128 chars minimum

### 2.2 Login
```
POST /api/v1/auth/login
```
**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "StrongPass1"
}
```
**Response (200):** Same token response as registration.

**Error Cases:**
| Status | Detail |
|--------|--------|
| 401 | Invalid email or password |
| 403 | Account is deactivated |

### 2.3 Token Refresh
```
POST /api/v1/auth/refresh
```
**Request Body:**
```json
{
  "refresh_token": "eyJhbG..."
}
```
**Response (200):** New access + refresh token pair.

### 2.4 Get Current User
```
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```
**Response (200):** User details.

### 2.5 Logout
```
POST /api/v1/auth/logout
Authorization: Bearer <access_token>
```
Blacklists the token in Redis (if enabled).

### 2.6 Password Reset
```
POST /api/v1/auth/forgot-password
Body: { "email": "user@example.com" }

POST /api/v1/auth/reset-password
Body: { "token": "reset-jwt-token", "new_password": "NewPass123" }
```

---

## 3. OAuth2 Social Login

### 3.1 Google OAuth2
```
GET /api/v1/auth/oauth/google          → Redirects to Google consent
GET /api/v1/auth/oauth/google/callback  → Handles callback, returns tokens
```

### 3.2 GitHub OAuth2
```
GET /api/v1/auth/oauth/github          → Redirects to GitHub consent
GET /api/v1/auth/oauth/github/callback  → Handles callback, returns tokens
```

**OAuth Flow:**
1. Client redirects user to `/auth/oauth/{provider}`
2. User authorizes on provider's consent screen
3. Provider redirects back to callback URL with `code`
4. Backend exchanges code for provider access token
5. Backend fetches user info from provider API
6. Backend creates/links user account
7. Backend returns JWT access + refresh tokens

---

## 4. JWT Token Structure

### Access Token
```json
{
  "sub": "user-uuid",
  "role": "user",
  "type": "access",
  "exp": 1720300800,
  "iat": 1720299000
}
```
- **Expiry:** 30 minutes (configurable)
- **Usage:** Authorization header for API requests

### Refresh Token
```json
{
  "sub": "user-uuid",
  "role": "user",
  "type": "refresh",
  "exp": 1720905600,
  "iat": 1720299000
}
```
- **Expiry:** 7 days (configurable)
- **Usage:** Obtaining new access tokens

### Password Reset Token
```json
{
  "sub": "user@example.com",
  "type": "password_reset",
  "exp": 1720302600
}
```
- **Expiry:** 1 hour

---

## 5. Role-Based Access Control (RBAC)

### 5.1 Role Hierarchy

| Role | Description | Access Level |
|------|-------------|--------------|
| `user` | Standard user | Own data only |
| `wellness_coach` | Health/wellness advisor | Own data + monitored users |
| `admin` | Platform administrator | Full platform access |

### 5.2 Endpoint Permissions

| Endpoint Group | user | wellness_coach | admin |
|---------------|------|----------------|-------|
| `POST /auth/*` | ✅ | ✅ | ✅ |
| `GET /auth/me` | ✅ | ✅ | ✅ |
| `GET,PUT /users/profile` | ✅ | ✅ | ✅ |
| `GET,PUT /users/profile/*` | ✅ | ✅ | ✅ |
| `CRUD /alarms/*` | ✅ | ✅ | ✅ |
| `GET /coach/users` | ❌ | ✅ | ✅ |
| `GET /coach/users/{id}/progress` | ❌ | ✅ | ✅ |
| `GET /admin/users` | ❌ | ❌ | ✅ |
| `PUT /admin/users/{id}/role` | ❌ | ❌ | ✅ |
| `PATCH /admin/users/{id}/activate` | ❌ | ❌ | ✅ |
| `PATCH /admin/users/{id}/deactivate` | ❌ | ❌ | ✅ |
| `DELETE /admin/users/{id}` | ❌ | ❌ | ✅ |
| `GET /admin/stats` | ❌ | ❌ | ✅ |

### 5.3 RBAC Implementation

The middleware layer (`auth_middleware.py`) provides:

```python
# Extract and validate JWT → return User
get_current_user(token, db) → User

# Ensure user is active
get_current_active_user(current_user) → User

# Role-based dependency factory
require_role(["admin"])  # Admin only
require_role(["admin", "wellness_coach"])  # Admin or Coach
```

**Usage in endpoints:**
```python
@router.get("/admin/users")
async def list_users(
    current_user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
):
    ...
```

---

## 6. Security Measures

| Feature | Implementation |
|---------|---------------|
| Password Hashing | bcrypt with auto-salt |
| JWT Signing | HS256 (HMAC-SHA256) |
| Token Blacklisting | Redis-backed (optional) |
| CORS | Configurable origin whitelist |
| Rate Limiting | slowapi (per-IP) |
| Input Validation | Pydantic v2 schemas |
| SQL Injection | SQLAlchemy ORM (parameterized) |
| Deactivation Guard | Checked on every request |

---

## 7. Configuration

All auth settings are managed via environment variables:

```env
SECRET_KEY=your-production-secret
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret
```

---

## 8. Authentication Flow Diagram

```
┌─────────┐     POST /register     ┌──────────┐
│  Client  │──────────────────────►│  Backend  │
│          │◄──────────────────────│           │
│          │  { access_token, ...} │  - Hash   │
│          │                       │  - Create │
│          │     POST /login       │  - JWT    │
│          │──────────────────────►│           │
│          │◄──────────────────────│           │
│          │  { access_token, ...} │           │
│          │                       │           │
│          │  GET /api/* + Bearer  │           │
│          │──────────────────────►│ Validate  │
│          │◄──────────────────────│ JWT +     │
│          │  { response data }    │ RBAC      │
│          │                       │           │
│          │  POST /refresh        │           │
│          │──────────────────────►│ Verify    │
│          │◄──────────────────────│ Refresh   │
│          │  { new tokens }       │ Token     │
└─────────┘                       └──────────┘
```

---

## 9. Testing

Run the authentication test suite:

```bash
cd backend
pytest tests/test_auth.py -v
pytest tests/test_rbac.py -v
```

**Test Coverage:**
- ✅ Registration (success, duplicate email/username, weak password)
- ✅ Login (success, wrong password, non-existent user, deactivated)
- ✅ Token refresh (success, invalid token, wrong token type)
- ✅ Current user (authenticated, unauthenticated, invalid token)
- ✅ Password reset (full flow, invalid token)
- ✅ RBAC enforcement (admin, coach, user access levels)
- ✅ Role changes (success, self-demotion prevention)
- ✅ Account activation/deactivation
