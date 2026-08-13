# Authentication Flow Documentation

## Intelligent Cognitive Alarm Platform — Authentication & Authorization

Verified against the implementation in `backend/app/api/v1/endpoints/auth.py`,
`backend/app/api/deps.py`, `backend/app/core/{security,cookies,oauth_state,rate_limit}.py`,
`backend/app/services/{auth_service,token_service}.py` and the SPA's
`frontend/src/services/api.js` + `frontend/src/store/authStore.js`.

---

## 1. Overview

The platform uses **JWT authentication with server-side revocation**:

- **Email/password** registration and login (the email field also accepts a username)
- **Google OAuth2** social login, protected by a signed, single-use `state` nonce
- **Two token transports** — HttpOnly session cookies (used by the SPA) and
  `Authorization: Bearer` (used by API clients and Swagger)
- **Token refresh** for seamless session continuity
- **Revocation** of individual tokens and of every session for an account
- **Email verification** and **password reset** via short-lived one-time JWTs
- **Brute-force protection** on the login and password-reset surfaces
- **Role-based access control** with three roles

> There is **no GitHub OAuth provider** and **no Redis token blacklist**.
> Revocation is persisted in the database (see §5).

---

## 2. Authentication endpoints

### 2.1 Registration

```
POST /api/v1/auth/register
```

**Request**

```json
{
  "email": "user@example.com",
  "username": "johndoe",
  "password": "StrongPass1",
  "full_name": "John Doe",
  "timezone": "Asia/Kolkata"
}
```

**Response — `201 Created`** (`UserResponse`; **no tokens are issued here**)

```json
{
  "id": 42,
  "email": "user@example.com",
  "username": "johndoe",
  "full_name": "John Doe",
  "role": "user",
  "is_active": true,
  "is_verified": false,
  "created_at": "2026-08-13T09:15:22Z"
}
```

Registration also provisions a default `UserProfile` (8 h sleep target, the
supplied timezone or `UTC`, `medium` difficulty) and sends a verification email
on a best-effort basis — a mail failure does not fail the registration.

**Validation**

| Field      | Rules                                                                  |
| ---------- | ---------------------------------------------------------------------- |
| `email`    | Valid address, unique                                                   |
| `username` | 3–100 characters, letters/digits/underscore only, unique                |
| `password` | 8–128 characters with at least one uppercase, one lowercase and one digit |
| `timezone` | Optional, ≤ 50 characters                                               |

**Errors** — `400 Email already registered` · `400 Username already taken` ·
`422` for schema violations.

### 2.2 Login

```
POST /api/v1/auth/login
```

**Request**

```json
{ "email": "user@example.com", "password": "StrongPass1" }
```

**Response — `200 OK`** (`LoginResponse`) plus `Set-Cookie` for both tokens:

```json
{
  "access_token": "eyJhbG...",
  "refresh_token": "eyJhbG...",
  "token_type": "bearer",
  "user": {
    "id": 42,
    "email": "user@example.com",
    "username": "johndoe",
    "full_name": "John Doe",
    "role": "user",
    "is_active": true,
    "is_verified": true
  }
}
```

There is no `expires_in` field; lifetimes are fixed by configuration (§4).

**Errors**

| Status | Detail                                                        |
| ------ | ------------------------------------------------------------- |
| `401`  | `Invalid email or password`                                    |
| `403`  | `Account is deactivated`                                       |
| `429`  | `Too many failed login attempts. Try again in N seconds.` (+ `Retry-After`) |

### 2.3 OAuth2 password form

```
POST /api/v1/auth/token        (application/x-www-form-urlencoded)
username=<email or username>&password=<password>
```

Returns `access_token` / `refresh_token` / `token_type` and sets the same
cookies. This is the endpoint behind Swagger UI's **Authorize** dialog.

### 2.4 Token refresh

```
POST /api/v1/auth/refresh
```

The refresh token is read from the request body **or** from the
`icap_refresh_token` cookie:

```json
{ "refresh_token": "eyJhbG..." }
```

**Response — `200 OK`**

```json
{ "access_token": "eyJhbG...", "refresh_token": "eyJhbG...", "token_type": "bearer" }
```

The access token being replaced is revoked as part of the exchange. `401` if
the refresh token is missing, malformed, expired, of the wrong type, revoked or
superseded.

### 2.5 Current user

```
GET  /api/v1/auth/me
PUT  /api/v1/auth/me      { "full_name": "...", "email": "..." }
```

`PUT /auth/me` is the **only** route that can change the account email;
`PUT /api/v1/users/profile` writes `full_name`, `username` and `timezone` only.

### 2.6 Logout

```
POST /api/v1/auth/logout        → { "message": "Logged out successfully", "user_id": 42 }
POST /api/v1/auth/logout-all    → { "message": "All sessions revoked", "user_id": 42 }
```

Both clear the session cookies. `logout` revokes the presented access token and
the refresh token by `jti`; `logout-all` moves the account's
`tokens_valid_after` watermark so every token issued before that moment is
rejected.

### 2.7 Email verification

```
POST /api/v1/auth/verify-email          { "token": "<jwt>" }
POST /api/v1/auth/resend-verification   { "email": "user@example.com" }
```

`resend-verification` always returns the same generic message so the endpoint
cannot be used to enumerate accounts, and it is rate limited.

### 2.8 Password reset

```
POST /api/v1/auth/forgot-password   { "email": "user@example.com" }
POST /api/v1/auth/reset-password    { "token": "<jwt>", "new_password": "NewPass123" }
```

`forgot-password` returns a generic message whether or not the address exists.
A successful reset revokes **every** existing session for the account.

When SMTP is not configured, verification and reset links are written to the
application log instead of being emailed.

---

## 3. Token transport

### 3.1 HttpOnly cookies (SPA)

`login`, `token`, `refresh` and the OAuth callback all call
`set_auth_cookies()`, which sets **both** tokens as cookies:

| Cookie                | Contains    | Attributes                                          |
| --------------------- | ----------- | --------------------------------------------------- |
| `icap_access_token`   | Access JWT  | `HttpOnly`, `Path=/`, `SameSite=Lax`, `Secure` in production, `Max-Age` = access lifetime |
| `icap_refresh_token`  | Refresh JWT | `HttpOnly`, `Path=/`, `SameSite=Lax`, `Secure` in production, `Max-Age` = refresh lifetime |

The React client therefore **never stores a JWT in `localStorage` or
`sessionStorage`**. It sends `withCredentials: true`, keeps only a non-sensitive
`icap_session` marker so it knows whether to attempt an authenticated call, and
refreshes reactively when a request returns `401`.

Names and attributes are configurable: `AUTH_COOKIE_ENABLED`,
`ACCESS_COOKIE_NAME`, `REFRESH_COOKIE_NAME`, `AUTH_COOKIE_SECURE`,
`AUTH_COOKIE_SAMESITE`, `AUTH_COOKIE_DOMAIN`.

### 3.2 Bearer header (API clients)

```
Authorization: Bearer <access_token>
```

`get_current_user` accepts the header **or** the cookie:
`oauth2_scheme_optional` (`auto_error=False`) reads the header, and
`access_cookie(request)` is the fallback. A `401` always carries
`WWW-Authenticate: Bearer`.

---

## 4. JWT structure

Signed with `SECRET_KEY` using **HS256** (`ALGORITHM`). In production the app
refuses to start with a missing, short or placeholder secret; outside production
it falls back to a constant, obviously insecure development key.

### Access token

```json
{
  "sub": "42",
  "role": "user",
  "jti": "0f5c…",
  "iat": 1786100000,
  "iat_ms": 1786100000123,
  "exp": 1786101800,
  "type": "access"
}
```

- `sub` is the numeric user id as a string. **The email is not a claim.**
- `jti` makes an individual token revocable.
- `iat_ms` exists because whole-second `iat` is too coarse to order a token
  against a revoke-all watermark taken moments earlier.
- Lifetime: `ACCESS_TOKEN_EXPIRE_MINUTES`, default **30 minutes**.

### Refresh token

Identical claims with `"type": "refresh"` and a lifetime of
`REFRESH_TOKEN_EXPIRE_DAYS`, default **7 days**.

### Password-reset token

```json
{ "sub": "42", "type": "password_reset", "exp": 1786103600 }
```

Lifetime `PASSWORD_RESET_TOKEN_EXPIRE_MINUTES`, default **60 minutes**.

### Email-verification token

```json
{ "sub": "42", "type": "email_verification", "exp": 1786186400 }
```

Lifetime `EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS`, default **24 hours**.

---

## 5. Session revocation

Revocation is persisted in the database, not in Redis.

| Mechanism                       | Where                                            | Effect                                          |
| ------------------------------- | ------------------------------------------------ | ----------------------------------------------- |
| `revoked_tokens` table          | `models/revoked_token.py`                        | A single `jti` is rejected from then on          |
| `users.tokens_valid_after`      | `models/user.py`                                 | Every token issued before the watermark is rejected |

`TokenRevocationService` is consulted on **every** authenticated request:
`get_current_user` rejects a token whose `jti` is revoked (`Token has been
revoked`) and one issued before the account watermark (`Session is no longer
valid`). The watermark is moved by `logout-all` and by a successful password
reset.

---

## 6. Google OAuth2

```
GET /api/v1/auth/oauth/google
    → 302 https://accounts.google.com/o/oauth2/v2/auth?...&state=<nonce>
      Set-Cookie: icap_oauth_state=<nonce>

GET /api/v1/auth/oauth/google/callback?code=...&state=...
    → 302 {FRONTEND_URL}/oauth/callback?status=success
      Set-Cookie: icap_access_token / icap_refresh_token
```

Flow:

1. The SPA sends the browser to `/auth/oauth/google`.
2. The backend mints a `state` nonce — `v1.<random>.<expiry>.<HMAC-SHA256>`
   signed with `SECRET_KEY` — and mirrors it into the HttpOnly
   `icap_oauth_state` cookie (`OAUTH_STATE_TTL_SECONDS`, default 600 s).
3. The user consents on Google's screen.
4. Google redirects back with `code` and `state`.
5. The backend validates `state` **before spending the authorization code**:
   the value must match the cookie, verify against the HMAC, be unexpired, and
   not have been redeemed before. Failures redirect to
   `{FRONTEND_URL}/login?error=oauth_state_...`.
6. The code is exchanged for a Google access token, the profile is fetched, and
   the account is created or linked.
7. Session cookies are set and the browser is redirected to
   `{FRONTEND_URL}/oauth/callback?status=success`. The SPA then calls
   `GET /auth/me`.

Two deliberate properties:

- **Tokens never appear in a redirect URL** — only `status=success` — so they
  cannot leak through browser history, proxy logs or the `Referer` header.
- The state cookie's `SameSite` is hard-coded to `lax` (not
  `AUTH_COOKIE_SAMESITE`): `strict` would drop the cookie on Google's
  top-level redirect back to the callback.

If Google credentials are not configured, `/auth/oauth/google` redirects to
`/login` with an explanatory error instead of failing.

---

## 7. Brute-force protection

Implemented in `core/rate_limit.py` as an in-process sliding window with
lockout, so limits apply per worker process. Disable with
`RATE_LIMIT_ENABLED=false`.

| Scope                        | Endpoints                                                                    | Limit | Window | On breach     |
| ---------------------------- | ---------------------------------------------------------------------------- | ----: | -----: | ------------- |
| Per account identifier       | `/auth/login`, `/auth/token`                                                 |     5 |  300 s | 900 s lockout |
| Per caller address           | `/auth/login`, `/auth/token`                                                 |    20 |  300 s | 900 s lockout |
| Per account **and** address  | `/auth/forgot-password`, `/auth/reset-password`, `/auth/resend-verification` |     3 |  900 s | 900 s cool-off |

The per-address cap is deliberately looser so a shared NAT address cannot lock
out unrelated users. A successful login clears the account's counter. Breaches
return `429` with `Retry-After`.

Login successes, failures, inactive-account attempts, lockouts, token
rejections and role denials are emitted as structured `app.security` log
records with password/token fields stripped and control characters scrubbed.

---

## 8. Role-based access control

### 8.1 Roles

| Role             | Description               | Access                                        |
| ---------------- | ------------------------- | --------------------------------------------- |
| `user`           | Standard user             | Own data only                                  |
| `wellness_coach` | Health/wellness advisor   | Own account + analytics for **assigned** clients |
| `admin`          | Platform administrator    | Full platform access                           |

### 8.2 Dependencies

`backend/app/api/deps.py` provides three dependencies — there is no
`auth_middleware.py` and no `require_role()` factory:

```python
get_current_user(request, token, db) -> User   # header or cookie; rejects revoked tokens
get_current_admin(current_user)      -> User   # 403 "Admin privileges required"
get_current_coach(current_user)      -> User   # 403 "Wellness coach privileges required"
```

`get_current_user` already rejects deactivated accounts with
`403 Inactive user`, so there is no separate `get_current_active_user`.

Usage:

```python
@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    ...
```

### 8.3 Endpoint permissions

| Endpoint group                                  | user | wellness_coach | admin |
| ----------------------------------------------- | :--: | :------------: | :---: |
| `POST /auth/register`, `/login`, `/refresh`     | ✅ (public) | ✅ | ✅ |
| `GET` / `PUT /auth/me`, `POST /auth/logout(-all)` | ✅ | ✅ | ✅ |
| `GET` / `PUT /users/profile*`                   | ✅ | ✅ | ✅ |
| `GET` / `PUT` / `PATCH /profiles/me*`           | ✅ | ✅ | ✅ |
| `CRUD /alarms/*`                                | ✅ | ✅ | ✅ |
| `/analytics/*`, `/dashboard/*`, `/recommendations/*`, `/reports/*`, `/notifications/*` | ✅ | ✅ | ✅ |
| `DELETE /users/account` (own account)           | ✅ | ✅ | ✅ |
| `GET /coach/overview`, `GET /coach/clients`     | ❌ | ✅ | ✅ |
| `GET /coach/clients/{id}/*`                     | ❌ | ✅ (assigned only) | ✅ (assigned only) |
| `GET /users/`, `GET` / `PUT` / `DELETE /users/{id}` | ❌ | ❌ | ✅ |
| `POST /users/{id}/activate`, `/deactivate`      | ❌ | ❌ | ✅ |
| `GET /admin/*`, `PUT /admin/notification-settings`, `POST /admin/announcements/broadcast` | ❌ | ❌ | ✅ |
| `GET` / `POST` / `DELETE /admin/coach-assignments` | ❌ | ❌ | ✅ |
| `GET /system/metrics`, `/alerts`, `/logging`    | ❌ | ❌ | ✅ |
| `GET /system/status`, `POST /system/client-errors`, `GET /`, `GET /health` | ✅ (public) | ✅ | ✅ |

Notes:

- Admin user management lives under **`/api/v1/users/{user_id}`**, not
  `/admin/users/{id}`. `GET /api/v1/admin/users` is a read-only, enriched
  listing.
- There is **no** `PUT .../users/{id}/role` endpoint. A role is changed through
  `PUT /api/v1/users/{user_id}` with `{"role": "wellness_coach"}`.
- Activate and deactivate are **`POST`**, not `PATCH`.
- Guards on self-targeting actions: an admin cannot change their own role,
  deactivate their own account, or delete their own account through the admin
  routes (`400`).
- A coach is scoped by `coach_assignments`; requesting an unassigned client
  returns `404`, and removing an assignment revokes access immediately.

### 8.4 Client-side routing

The SPA mirrors these rules in `frontend/src/utils/routeAccess.js` and
`App.jsx` — `/wellness` is limited to `wellness_coach`, `/admin` to `admin`, and
a denied route renders the **Access Denied** page. This is a usability layer
only; the API is the security boundary.

---

## 9. Security measures

| Feature                | Implementation                                                                |
| ---------------------- | ----------------------------------------------------------------------------- |
| Password hashing       | bcrypt with per-password salt (`app/utils/hashing.py`)                        |
| JWT signing            | HS256, with production key strength enforced at startup                        |
| Token revocation       | `revoked_tokens` table + `users.tokens_valid_after` watermark (no Redis)       |
| Session transport      | HttpOnly, `SameSite`-constrained cookies; `Secure` mandatory in production      |
| OAuth CSRF             | Signed, expiring, single-use `state` bound to an HttpOnly cookie               |
| Rate limiting          | In-process sliding window in `core/rate_limit.py` (no third-party limiter)      |
| Account enumeration    | Generic responses on forgot-password and resend-verification                    |
| CORS                   | Configurable origin allow-list + credentials                                    |
| Input validation       | Pydantic v2 schemas                                                             |
| SQL injection          | SQLAlchemy ORM with parameterized queries                                       |
| Deactivation guard     | Checked on every authenticated request                                          |
| Security audit logging | `app.security` structured records with secrets stripped and inputs scrubbed     |
| Docs exposure          | `/docs`, `/redoc`, `/openapi.json` are not registered in production            |

---

## 10. Configuration

```env
# Core
ENVIRONMENT=production            # production enforces a strong key + Secure cookies
SECRET_KEY=<at least 32 random characters>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES=60
EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS=24

# Session cookies
AUTH_COOKIE_ENABLED=true
ACCESS_COOKIE_NAME=icap_access_token
REFRESH_COOKIE_NAME=icap_refresh_token
AUTH_COOKIE_SECURE=              # blank → derived from ENVIRONMENT
AUTH_COOKIE_SAMESITE=lax
AUTH_COOKIE_DOMAIN=

# Brute-force protection
RATE_LIMIT_ENABLED=true
LOGIN_MAX_ATTEMPTS=5
LOGIN_IP_MAX_ATTEMPTS=20
LOGIN_ATTEMPT_WINDOW_SECONDS=300
LOGIN_LOCKOUT_SECONDS=900
PASSWORD_RESET_MAX_REQUESTS=3
PASSWORD_RESET_WINDOW_SECONDS=900

# Google OAuth2 (note the OAUTH2_ prefix)
OAUTH2_GOOGLE_CLIENT_ID=
OAUTH2_GOOGLE_CLIENT_SECRET=
OAUTH2_GOOGLE_REDIRECT_URI=https://your-host/api/v1/auth/oauth/google/callback
OAUTH_STATE_COOKIE_NAME=icap_oauth_state
OAUTH_STATE_TTL_SECONDS=600

# SPA origin used by OAuth and email links
FRONTEND_URL=http://localhost:3000
```

---

## 11. Flow diagram

```
┌────────┐   POST /auth/register    ┌───────────┐
│ Client │─────────────────────────►│  Backend  │  hash → create user + profile
│        │◄─────────────────────────│           │  201 UserResponse (no tokens)
│        │                          │           │
│        │   POST /auth/login       │           │  rate-limit → verify → issue JWTs
│        │─────────────────────────►│           │
│        │◄─────────────────────────│           │  200 + Set-Cookie (access, refresh)
│        │                          │           │
│        │   GET /api/v1/...        │           │  cookie OR bearer → verify sig
│        │─────────────────────────►│           │  → jti revoked? → watermark?
│        │◄─────────────────────────│           │  → active? → role check
│        │                          │           │
│        │   401 → POST /auth/refresh          │  verify refresh → revoke old
│        │─────────────────────────►│           │  access → issue new pair
│        │◄─────────────────────────│           │
│        │                          │           │
│        │   POST /auth/logout(-all)│           │  revoke jti / move watermark
│        │─────────────────────────►│           │  + clear cookies
└────────┘                          └───────────┘
```

---

## 12. Testing

```bash
cd backend
pytest tests/test_auth.py -v            # registration, login, refresh, me, reset
pytest tests/test_auth_security.py -v   # cookies, revocation, rate limits, OAuth state CSRF
pytest tests/test_rbac.py tests/test_rbac_matrix.py -v
pytest tests/test_route_aliases.py -v   # proves /auth/me vs /users/profile differ
```

Covered:

- Registration — success, duplicate email/username, weak password
- Login — success, wrong password, unknown user, deactivated account, lockout
- Cookie transport — cookies set on login, accepted without a header, cleared on logout
- Token refresh — success, invalid token, wrong token type, revoked token
- Revocation — logout, logout-all, password-reset invalidation
- OAuth `state` — missing, mismatched, tampered, expired and replayed nonces
- Password reset and email verification, including generic-response behaviour
- RBAC — per-role access across the whole route matrix, and self-targeting guards
