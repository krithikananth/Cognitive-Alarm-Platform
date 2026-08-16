# 📡 API Documentation

## Intelligent Cognitive Alarm Platform (ICAP)

This reference describes the API as it is implemented today. It was written
against the live OpenAPI schema (`app.openapi()`) and hand-checked against the
route handlers. The authoritative, always-current contract is the OpenAPI
document itself — see [§1.2](#12-interactive-documentation).

---

## 1. Overview

| Property           | Value                                                            |
| ------------------ | ---------------------------------------------------------------- |
| **API version**    | `v1`                                                             |
| **App version**    | `1.0.0`                                                          |
| **Base path**      | `/api/v1`                                                        |
| **Local base URL** | `http://localhost:8000/api/v1`                                   |
| **Docker base URL**| `https://localhost/api/v1` (Nginx edge, TLS)                     |
| **Format**         | JSON (report exports return PDF/XLSX; Prometheus returns text)   |
| **Auth**           | HttpOnly session cookies **or** `Authorization: Bearer <jwt>`    |
| **Routes**         | 132 — 130 under `/api/v1`, plus `GET /` and `GET /health`        |

### 1.1 Route groups

| Tag              | Prefix                    | Routes | Access                      |
| ---------------- | ------------------------- | -----: | --------------------------- |
| Root             | `/`                       |      1 | Public                      |
| Health           | `/health`                 |      1 | Public                      |
| Authentication   | `/api/v1/auth`            |     14 | Public + authenticated      |
| Users            | `/api/v1/users`           |     14 | Authenticated + admin       |
| User Profiles    | `/api/v1/profiles`        |      6 | Authenticated               |
| Alarm Scheduling | `/api/v1/alarms`          |     24 | Authenticated               |
| Analytics        | `/api/v1/analytics`       |     14 | Authenticated               |
| Dashboard        | `/api/v1/dashboard`       |      5 | Authenticated               |
| Recommendations  | `/api/v1/recommendations` |      8 | Authenticated               |
| Reports          | `/api/v1/reports`         |      3 | Authenticated               |
| Notifications    | `/api/v1/notifications`   |      9 | Authenticated               |
| Wellness Coach   | `/api/v1/coach`           |     10 | `wellness_coach` or `admin` |
| Admin            | `/api/v1/admin`           |     17 | `admin`                     |
| System           | `/api/v1/system`          |      6 | Mixed — see §12             |

### 1.2 Interactive documentation

| Surface      | Path            |
| ------------ | --------------- |
| Swagger UI   | `/docs`         |
| ReDoc        | `/redoc`        |
| OpenAPI JSON | `/openapi.json` |

> ⚠️ These routes are **not registered when `ENVIRONMENT=production`** (override
> with `ENABLE_API_DOCS=true`). The Docker Compose stack sets
> `ENABLE_API_DOCS=false` by default and Nginx additionally returns `404` for
> `/docs`, `/redoc` and `/openapi.json`. Requesting them on a production
> deployment yields `404`, not `401`.

---

## 2. Authentication

ICAP issues **JWT** access and refresh tokens. There are two transports and both
are accepted on every protected route:

1. **HttpOnly cookies** — set automatically by `POST /auth/login`,
   `POST /auth/token`, `POST /auth/refresh` and the Google OAuth callback. This
   is what the React SPA uses; it never stores a JWT in JavaScript.
2. **`Authorization: Bearer <access_token>`** — for API clients, scripts and the
   Swagger *Authorize* button.

### 2.1 Cookies

| Cookie               | Contains    | Path | Attributes                                        |
| -------------------- | ----------- | ---- | ------------------------------------------------- |
| `icap_access_token`  | Access JWT  | `/`  | `HttpOnly`, `SameSite=Lax`, `Secure` in production |
| `icap_refresh_token` | Refresh JWT | `/`  | `HttpOnly`, `SameSite=Lax`, `Secure` in production |
| `icap_oauth_state`   | OAuth nonce | `/`  | `HttpOnly`, `SameSite=Lax`, 10 min TTL, single use |

Cookie names, `SameSite`, `Secure` and an optional domain are configurable
(`ACCESS_COOKIE_NAME`, `REFRESH_COOKIE_NAME`, `AUTH_COOKIE_SAMESITE`,
`AUTH_COOKIE_SECURE`, `AUTH_COOKIE_DOMAIN`). Cookie auth can be disabled with
`AUTH_COOKIE_ENABLED=false`, leaving bearer tokens only.

Browser clients must send credentials (`withCredentials: true` in axios,
`credentials: 'include'` in `fetch`).

### 2.2 Bearer header

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 2.3 Token lifetimes and revocation

| Token   | Default lifetime | Setting                       |
| ------- | ---------------- | ----------------------------- |
| Access  | 30 minutes       | `ACCESS_TOKEN_EXPIRE_MINUTES` |
| Refresh | 7 days           | `REFRESH_TOKEN_EXPIRE_DAYS`   |

Tokens carry a `jti` and revocation is enforced server-side:

- `POST /auth/logout` revokes the presented access token and the refresh token.
- `POST /auth/logout-all` moves the account's `tokens_valid_after` marker, so
  **every** previously issued token is rejected.
- A successful password reset performs the same account-wide invalidation.
- `POST /auth/refresh` revokes the access token it replaces.

A revoked or superseded token returns `401` with `WWW-Authenticate: Bearer`.

### 2.4 Roles

`user` · `wellness_coach` · `admin`

- `/api/v1/coach/*` requires `wellness_coach` **or** `admin`.
- `/api/v1/admin/*`, the admin-only routes under `/api/v1/users`, and
  `GET /api/v1/system/metrics|alerts|logging` require `admin`.
- Everything else requires any authenticated, active account.
- A deactivated account receives `403 {"detail": "Inactive user"}`.

---

## 3. Request/response conventions

### 3.1 Response headers

| Header             | Emitted on                     | Meaning                                                                                                                                                  |
| ------------------ | ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `X-Request-ID`     | Every response                 | Correlation id. An inbound value matching `[A-Za-z0-9._:-]{1,64}` is honoured, otherwise one is generated. Header name is configurable (`REQUEST_ID_HEADER`). |
| `X-Process-Time`   | Every response (incl. 4xx/5xx) | Server processing time in milliseconds, 2 dp.                                                                                                             |
| `Retry-After`      | `429` responses                | Seconds until the caller may retry.                                                                                                                       |
| `WWW-Authenticate` | `401` responses                | Always `Bearer`.                                                                                                                                          |

> There are **no** `X-RateLimit-*` headers. Rate-limit state is communicated
> through `429` + `Retry-After` only.

### 3.2 Error format

All handled errors use FastAPI's standard envelope:

```json
{ "detail": "Human-readable error message" }
```

Validation failures (`422`) use the Pydantic v2 array form:

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "email"],
      "msg": "value is not a valid email address: An email address must have an @-sign.",
      "input": "not-an-email"
    }
  ]
}
```

Maintenance mode adds one extra key (see [§13](#13-maintenance-mode)):

```json
{ "detail": "We are performing scheduled maintenance.", "maintenance_mode": true }
```

### 3.3 Status codes in use

| Code  | Used for                                                                                                      |
| ----- | ------------------------------------------------------------------------------------------------------------- |
| `200` | Successful `GET` / `PUT` / `PATCH` / `POST` that returns a body                                                 |
| `201` | Resource created — register, create alarm, event ingest, device token, coach assignment, broadcast              |
| `202` | Accepted — `POST /system/client-errors`                                                                         |
| `204` | Deleted/cleared with no body — delete alarm, delete account, delete user, remove assignment, clear feedback      |
| `302` | OAuth redirects — `/auth/oauth/google`, `/auth/oauth/google/callback`                                            |
| `400` | Business-rule rejection — duplicate email/username, invalid date window, no active wake cycle, unknown report type |
| `401` | Missing, malformed, expired, revoked or superseded credentials                                                  |
| `403` | Authenticated but not permitted — wrong role, deactivated account                                               |
| `404` | Resource does not exist or is not visible to the caller                                                          |
| `409` | Conflicting state — e.g. `fail-wake` after the wake was already verified                                         |
| `422` | Schema/query validation error                                                                                    |
| `429` | Login or password-reset rate limit hit                                                                           |
| `500` | Unhandled server error                                                                                           |
| `503` | Maintenance mode is on and the request is a non-admin write                                                      |

> Duplicate email/username on registration returns **`400`**, not `409`.

### 3.4 Pagination

Most list endpoints use **page-based** pagination and echo the page in the body:

```http
GET /api/v1/alarms/?page=2&per_page=20
```

```json
{ "alarms": [], "total": 37, "page": 2, "per_page": 20 }
```

| Parameter  | Default | Range                                                  |
| ---------- | ------- | ------------------------------------------------------ |
| `page`     | `1`     | `>= 1`                                                 |
| `per_page` | `20`    | `1–100` (`1–200` for analytics events; `50` default for admin coach assignments) |

Admin and coach collections additionally return `total_pages`.

The one exception is `GET /api/v1/users/` (admin), which uses offset pagination
(`skip`, default `0`; `limit`, default `100`) and returns a bare array.

### 3.5 Date windows

Analytics, dashboard and coach endpoints accept a rolling window:

| Parameter | Default | Range   |
| --------- | ------- | ------- |
| `days`    | `30`    | `1–365` |

Reports and admin analytics accept **either** `days` **or** an explicit
inclusive range:

| Parameter    | Notes                                                           |
| ------------ | --------------------------------------------------------------- |
| `days`       | Calendar days ending today (inclusive). Clamped to `1–365`.      |
| `start_date` | `YYYY-MM-DD`. Must be sent together with `end_date`.             |
| `end_date`   | `YYYY-MM-DD`. Must be on or after `start_date`. Span ≤ 365 days. |

Sending `days` together with `start_date`/`end_date`, sending only one side of
the range, inverting the range, or exceeding 365 days returns `400`.

### 3.6 Enumerations

| Enum                     | Values                                                                                                                                      |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `UserRole`               | `user`, `wellness_coach`, `admin`                                                                                                            |
| `AlarmType`              | `daily`, `weekday`, `weekend`, `one_time`, `smart_adaptive`                                                                                  |
| `ChallengeType`          | `math`, `logic`, `memory`, `word_game`, `word`, `pattern`, `riddle`, `quiz`, `random`                                                        |
| `DifficultyPreference`   | `beginner`, `easy`, `medium`, `hard`, `expert`                                                                                               |
| `RecommendationCategory` | `sleep`, `wake`, `habit`, `productivity`, `challenge`                                                                                        |
| `RecommendationPriority` | `high`, `medium`, `low`                                                                                                                      |
| `RecommendationRating`   | `helpful`, `not_helpful`, `dismissed`                                                                                                        |
| `NotificationType`       | `bedtime_reminder`, `wake_reminder`, `alarm_trigger`, `habit_alert`, `challenge_reminder`, `progress_update`, `motivational`, `announcement` |
| `NotificationStatus`     | `pending`, `sent`, `delivered`, `failed`, `read`                                                                                             |
| `NotificationSound`      | `default`, `gentle`, `chime`, `silent`                                                                                                       |
| `NotificationFrequency`  | `all`, `essential`, `minimal`                                                                                                                |
| `DeviceType`             | `web`, `ios`, `android`                                                                                                                      |
| Report type (user)       | `habit`, `wake`, `challenge`, `productivity`, `sleep`                                                                                        |
| Report type (system)     | `user`, `alarm`, `habit`, `platform`                                                                                                         |

---

## 4. Authentication endpoints

| Method | Path                                 | Auth | Description                                     |
| ------ | ------------------------------------ | ---- | ----------------------------------------------- |
| POST   | `/api/v1/auth/register`              | ❌    | Create an account (`201`)                       |
| POST   | `/api/v1/auth/login`                 | ❌    | Email/username + password → tokens + cookies    |
| POST   | `/api/v1/auth/token`                 | ❌    | OAuth2 password form flow (Swagger *Authorize*) |
| POST   | `/api/v1/auth/refresh`               | ❌\*  | Exchange a refresh token for a new pair         |
| POST   | `/api/v1/auth/logout`                | 🔑    | Revoke the current session                      |
| POST   | `/api/v1/auth/logout-all`            | 🔑    | Revoke every session for the account            |
| GET    | `/api/v1/auth/me`                    | 🔑    | Current user                                    |
| PUT    | `/api/v1/auth/me`                    | 🔑    | Update `full_name` / `email`                    |
| POST   | `/api/v1/auth/verify-email`          | ❌    | Consume an email-verification token             |
| POST   | `/api/v1/auth/resend-verification`   | ❌    | Re-send the verification email                  |
| POST   | `/api/v1/auth/forgot-password`       | ❌    | Request a reset link                            |
| POST   | `/api/v1/auth/reset-password`        | ❌    | Consume a reset token, set a new password       |
| GET    | `/api/v1/auth/oauth/google`          | ❌    | Redirect to Google consent (`302`)              |
| GET    | `/api/v1/auth/oauth/google/callback` | ❌    | Google redirects here (`302` back to the SPA)   |

\* `/auth/refresh` needs a valid refresh token — supplied in the body or the
refresh cookie — but not an access token.

### `POST /api/v1/auth/register`

**Body**

```json
{
  "email": "user@example.com",
  "username": "johndoe",
  "password": "SecureP@ss123",
  "full_name": "John Doe",
  "timezone": "Asia/Kolkata"
}
```

| Field       | Rules                                                                    |
| ----------- | ------------------------------------------------------------------------ |
| `email`     | Valid address, unique                                                     |
| `username`  | 3–100 characters, letters/digits/underscore only, unique                  |
| `password`  | 8–128 characters, at least one uppercase, one lowercase and one digit      |
| `full_name` | Optional, ≤ 255 characters                                                |
| `timezone`  | Optional IANA name (≤ 50 chars); defaults to `UTC` and seeds the profile   |

**`201 Created`** — returns the user only. **No tokens are issued here**; call
`/auth/login` next.

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

A verification email is sent best-effort; registration still succeeds if mail
delivery fails. When SMTP is not configured the verification link is written to
the application log instead.

**`400 Bad Request`** — `Email already registered` or `Username already taken`.

### `POST /api/v1/auth/login`

**Body**

```json
{ "email": "user@example.com", "password": "SecureP@ss123" }
```

`email` also accepts the account's username.

**`200 OK`** — sets the `icap_access_token` and `icap_refresh_token` cookies and
returns:

```json
{
  "access_token": "eyJhbGciOi...",
  "refresh_token": "eyJhbGciOi...",
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

**Errors** — `401 Invalid email or password` · `403 Account is deactivated` ·
`429` once the lockout threshold is crossed (see §11).

### `POST /api/v1/auth/token`

`application/x-www-form-urlencoded` with `username` (email **or** username) and
`password`. Returns `access_token` / `refresh_token` / `token_type` and also
sets the session cookies. This is the endpoint Swagger's *Authorize* dialog uses.

### `POST /api/v1/auth/refresh`

**Body** — optional when the refresh cookie is present:

```json
{ "refresh_token": "eyJhbGciOi..." }
```

**`200 OK`**

```json
{ "access_token": "eyJhbGciOi...", "refresh_token": "eyJhbGciOi...", "token_type": "bearer" }
```

The replaced access token is revoked. `401` if the refresh token is missing,
invalid, expired or revoked.

### `POST /api/v1/auth/logout` · `POST /api/v1/auth/logout-all`

**`200 OK`**

```json
{ "message": "Logged out successfully", "user_id": 42 }
```

`logout-all` returns `{"message": "All sessions revoked", "user_id": 42}`. Both
clear the session cookies; `logout-all` invalidates every token issued to the
account before the call.

### `GET|PUT /api/v1/auth/me`

`PUT` accepts `{"full_name": "...", "email": "..."}`. This is the **only** route
that can change the account email — `PUT /users/profile` cannot.

### Email verification and password reset

| Endpoint                         | Body                                        | Response                     |
| -------------------------------- | ------------------------------------------- | ---------------------------- |
| `POST /auth/verify-email`        | `{"token": "<jwt>"}`                        | `{"message": "..."}`         |
| `POST /auth/resend-verification` | `{"email": "user@example.com"}`             | Generic `{"message": "..."}` |
| `POST /auth/forgot-password`     | `{"email": "user@example.com"}`             | Generic `{"message": "..."}` |
| `POST /auth/reset-password`      | `{"token": "<jwt>", "new_password": "..."}` | `{"message": "..."}`         |

`forgot-password` and `resend-verification` always return the same generic
message whether or not the address exists — this prevents account enumeration.
A successful reset revokes every existing session for that account.

### Google OAuth2

```
GET /api/v1/auth/oauth/google
    → 302 https://accounts.google.com/o/oauth2/v2/auth?...&state=<nonce>
      Set-Cookie: icap_oauth_state=<nonce>   (HttpOnly, SameSite=Lax, 10 min, single use)

GET /api/v1/auth/oauth/google/callback?code=...&state=...
    → 302 {FRONTEND_URL}/oauth/callback?status=success
      Set-Cookie: icap_access_token / icap_refresh_token
```

- The `state` nonce is HMAC-signed, bound to the cookie, expiring and single
  use. A mismatch, replay or expiry redirects to
  `{FRONTEND_URL}/login?error=...` **before** the authorization code is spent.
- **Tokens are never placed in the redirect URL** — only `status=success`.
- If Google credentials are not configured, the start route redirects to
  `/login?error=Google sign-in is not configured...`.

---

## 5. Users

| Method | Path                                   | Auth | Description                                |
| ------ | -------------------------------------- | ---- | ------------------------------------------ |
| GET    | `/api/v1/users/profile`                | 🔑    | Account + nested profile bundle            |
| PUT    | `/api/v1/users/profile`                | 🔑    | Update `full_name`, `username`, `timezone` |
| GET    | `/api/v1/users/profile/preferences`    | 🔑    | Challenge types, difficulty, goals, habits |
| PUT    | `/api/v1/users/profile/preferences`    | 🔑    | Update preferences → returns the bundle    |
| PUT    | `/api/v1/users/profile/goals`          | 🔑    | Update productivity goals (lenient)        |
| PUT    | `/api/v1/users/profile/sleep-schedule` | 🔑    | Preferred wake time + sleep duration       |
| GET    | `/api/v1/users/profile/stats`          | 🔑    | Habit score, streaks, weekly tracker       |
| DELETE | `/api/v1/users/account`                | 🔑    | Delete own account (`204`)                 |
| GET    | `/api/v1/users/`                       | 👑    | List users (`skip`, `limit`) — bare array  |
| GET    | `/api/v1/users/{user_id}`              | 👑    | Fetch one user                             |
| PUT    | `/api/v1/users/{user_id}`              | 👑    | Update name/email/role/active flag         |
| POST   | `/api/v1/users/{user_id}/activate`     | 👑    | Reactivate an account                      |
| POST   | `/api/v1/users/{user_id}/deactivate`   | 👑    | Deactivate an account                      |
| DELETE | `/api/v1/users/{user_id}`              | 👑    | Delete an account (`204`)                  |

🔑 authenticated · 👑 admin only

### `GET /api/v1/users/profile`

```json
{
  "id": 42,
  "email": "user@example.com",
  "username": "johndoe",
  "full_name": "John Doe",
  "role": "user",
  "timezone": "Asia/Kolkata",
  "is_active": true,
  "profile": {
    "preferred_wakeup_time": "06:30",
    "sleep_duration_hours": 7.5,
    "difficulty_preference": "medium",
    "adapted_difficulty": "hard",
    "productivity_goals": ["Wake up by 6 AM", "Exercise daily"],
    "habit_preferences": { "preferred_challenge_types": ["math", "logic"] },
    "habit_score": 78.4,
    "streak_days": 12
  }
}
```

### `PUT /api/v1/users/profile/preferences`

```json
{
  "preferred_challenge_types": ["math", "logic"],
  "difficulty_preference": "hard",
  "productivity_goals": "Wake up by 6 AM, exercise daily"
}
```

`productivity_goals` is lenient here and on `PUT /users/profile/goals`: a
comma-separated string is split into a list. The response is the **profile
bundle**, not the preferences object.

---

## 6. User Profiles (`/profiles`)

A second, stricter surface over the same `user_profiles` row. It is retained
deliberately — it exposes fields the `/users/profile` bundle does not.

| Method | Path                                 | Description                                                                                                    |
| ------ | ------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/profiles/me`                | Full profile incl. `adapted_difficulty`, `wake_up_consistency_score`, `total_alarms_dismissed`, `total_snoozes` |
| PUT    | `/api/v1/profiles/me`                | Bulk update of the six profile fields                                                                          |
| PATCH  | `/api/v1/profiles/me/sleep-schedule` | `preferred_wake_time`, `sleep_duration_hours`                                                                  |
| PATCH  | `/api/v1/profiles/me/goals`          | `productivity_goals` — **typed list required** (`422` on a plain string)                                        |
| PATCH  | `/api/v1/profiles/me/habits`         | `habit_preferences` object                                                                                     |
| GET    | `/api/v1/profiles/me/habit-score`    | Habit score, component breakdown and weights                                                                    |

### `GET /api/v1/profiles/me/habit-score`

```json
{
  "habit_score": 78.4,
  "breakdown": {
    "wake_up_consistency": 82.0,
    "challenge_completion": 74.0,
    "snooze_reduction": 71.0,
    "sleep_adherence": 80.0
  },
  "weights": {
    "wake_up_consistency": 0.35,
    "challenge_completion": 0.25,
    "snooze_reduction": 0.2,
    "sleep_adherence": 0.2
  },
  "success_streak": 4,
  "failure_streak": 0,
  "streak_days": 12
}
```

---

## 7. Alarms and challenges

### 7.1 Alarm CRUD

| Method | Path                               | Description                                       |
| ------ | ---------------------------------- | ------------------------------------------------- |
| GET    | `/api/v1/alarms/`                  | List (`page`, `per_page`, `is_active`)            |
| POST   | `/api/v1/alarms/`                  | Create (`201`)                                    |
| GET    | `/api/v1/alarms/{alarm_id}`        | Fetch one                                         |
| PUT    | `/api/v1/alarms/{alarm_id}`        | Update                                            |
| DELETE | `/api/v1/alarms/{alarm_id}`        | Delete (`204`)                                    |
| PATCH  | `/api/v1/alarms/{alarm_id}/toggle` | `{"is_active": true}` / `{"is_active": false}`    |
| GET    | `/api/v1/alarms/upcoming`          | Next triggers (`hours_ahead`, 1–168, default 24)  |

**`POST /api/v1/alarms/`**

```json
{
  "title": "Morning Workout",
  "description": "Gym day",
  "alarm_time": "06:30",
  "alarm_type": "weekday",
  "days_of_week": [0, 1, 2, 3, 4],
  "one_time_date": null,
  "snooze_limit": 2,
  "snooze_interval_minutes": 5,
  "challenge_type": "math",
  "challenge_count": 1,
  "challenge_difficulty": "medium",
  "volume": 80,
  "vibrate": true,
  "label": "Workout"
}
```

| Field                  | Notes                                                                                                                                                                          |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `alarm_time`           | **Required.** `HH:MM` or `HH:MM:SS`, interpreted in the profile timezone                                                                                                        |
| `alarm_type`           | `daily` (default), `weekday`, `weekend`, `one_time`, `smart_adaptive`                                                                                                           |
| `days_of_week`         | `0 = Monday … 6 = Sunday`. **Narrows** the type's base set — a `weekday` alarm cannot select Sunday. An empty or disjoint selection falls back to the base set, so an alarm is never unschedulable |
| `one_time_date`        | `YYYY-MM-DD`, used by `one_time` alarms. It is stored, so editing the time or toggling the alarm off/on does not reschedule it to today                                          |
| `snooze_limit`         | `0` enables anti-snooze — snoozing is refused                                                                                                                                    |
| `snooze_interval_minutes` | Delay applied per snooze                                                                                                                                                     |
| `challenge_type`       | Any `ChallengeType`; `random` picks per ring using the profile's habit preferences                                                                                               |
| `challenge_count`      | Number of consecutive challenges required to dismiss                                                                                                                             |
| `challenge_difficulty` | Optional override of the profile's adapted difficulty                                                                                                                            |
| `volume`               | `0–100`                                                                                                                                                                          |

The response (`AlarmResponse`) adds `id`, `user_id`, `is_active`,
`next_trigger_at`, `last_triggered_at`, `total_dismissals`, `total_snoozes`,
`created_at` and `updated_at`.

### 7.2 The wake cycle

```
GET  /alarms/{id}/challenge     → serve a challenge and open a wake cycle
POST /alarms/{id}/verify        → submit an answer (repeat for multi-step)
POST /alarms/{id}/dismiss       → dismiss using the verification token
POST /alarms/{id}/snooze        → snooze (difficulty escalates)
POST /alarms/{id}/fail-wake     → abandon the cycle
```

| Method | Path                                    | Description                                                       |
| ------ | --------------------------------------- | ----------------------------------------------------------------- |
| GET    | `/api/v1/alarms/{alarm_id}/challenge`   | Serve the current challenge; records a challenge *delivery*        |
| POST   | `/api/v1/alarms/{alarm_id}/verify`      | Verify an answer; advances the step or completes the wake          |
| POST   | `/api/v1/alarms/{alarm_id}/dismiss`     | Dismiss with `{"verification_token": "..."}`                       |
| POST   | `/api/v1/alarms/{alarm_id}/snooze`      | Snooze; `400` when the limit is reached or anti-snooze is on       |
| POST   | `/api/v1/alarms/{alarm_id}/fail-wake`   | Record a failed wake; `400` with no open cycle, `409` once verified |
| GET    | `/api/v1/alarms/{alarm_id}/snooze-info` | Snooze count/limit, escalation level, next difficulty              |

**`GET /alarms/{alarm_id}/challenge` → `ChallengeResponse`**

```json
{
  "type": "MATH",
  "prompt": "What is 47 + 68?",
  "options": null,
  "difficulty": "medium",
  "time_limit_seconds": 60,
  "requested_type": "random",
  "selection_reason": "preferred_challenge_types",
  "adaptive_difficulty": { "baseline": "medium", "escalation_level": 0 },
  "source": "ai",
  "ai_generated": true,
  "generator": "gemini-1.5-flash",
  "current_step": 1,
  "total_steps": 2,
  "consecutive_correct": 0,
  "required_correct": 2,
  "escalation_level": 0,
  "requires_consecutive": true
}
```

`source` is `ai` or `procedural`. AI generation is attempted only when
`AI_CHALLENGE_ENABLED` is on and `GEMINI_API_KEY` is set; it is never used for
`memory` challenges (the prompt *is* the sequence), and any failure falls back
to the deterministic procedural generators.

**`POST /alarms/{alarm_id}/verify`**

```json
{
  "user_answer": "115",
  "time_taken_seconds": 8,
  "failed_attempts": 0,
  "challenge_prompt": "What is 47 + 68?",
  "challenge_difficulty": "medium",
  "challenge_step": 1,
  "challenge_total_steps": 2
}
```

The response (`ChallengeVerifyResponse`) carries `status`, `message`,
`current_step` / `total_steps`, `consecutive_correct` / `required_correct`,
`is_dismissed`, `verification_token` (present once the wake is confirmed),
`wake_confirmed`, `score`, `wakefulness`, `alarm` and the streak counters.

### 7.3 Practice, history and analysis

| Method | Path                                          | Description                                                 |
| ------ | --------------------------------------------- | ----------------------------------------------------------- |
| POST   | `/api/v1/alarms/challenge/practice`           | Start a practice challenge (`challenge_type`, `difficulty`) |
| POST   | `/api/v1/alarms/challenge/practice/verify`    | Score a practice answer                                     |
| GET    | `/api/v1/alarms/challenge/stats`              | Lifetime accuracy, response time, by type/difficulty        |
| GET    | `/api/v1/alarms/challenge/history`            | All attempts (`page`, `per_page`)                           |
| GET    | `/api/v1/alarms/{alarm_id}/challenge/history` | Attempts for one alarm                                      |
| GET    | `/api/v1/alarms/challenge/analysis`           | Strengths/weaknesses, completion, personalization block     |
| GET    | `/api/v1/alarms/challenge/learning-profile`   | Learning patterns, engagement, projected difficulty         |
| GET    | `/api/v1/alarms/challenge/log-health`         | Attempt-log audit; `?repair=true` repairs the caller's rows |

Practice attempts are deliberately excluded from wake streaks, habit logs and
the attempt log.

### 7.4 Wake history

| Method | Path                                | Description                                       |
| ------ | ----------------------------------- | ------------------------------------------------- |
| GET    | `/api/v1/alarms/snooze-history`     | Snooze audit events (`limit`, 1–200, default 50)  |
| GET    | `/api/v1/alarms/wake-confirmations` | Confirmed wake events (`limit`, 1–100, default 20)|
| GET    | `/api/v1/alarms/wakefulness`        | Current wakefulness score, level and factors      |

---

## 8. Analytics

All routes accept `days` (`1–365`, default `30`) unless stated otherwise.

| Method | Path                                                    | Description                                                   |
| ------ | ------------------------------------------------------- | ------------------------------------------------------------- |
| POST   | `/api/v1/analytics/events`                              | Ingest one event (`201`)                                      |
| POST   | `/api/v1/analytics/events/batch`                        | Ingest many events (`201`)                                    |
| GET    | `/api/v1/analytics/events`                              | List events (`page`, `per_page` ≤ 200, `event_type`, `entity_type`, `entity_id`) |
| GET    | `/api/v1/analytics/summary`                             | Event counts by type (no window)                              |
| GET    | `/api/v1/analytics/behavioral`                          | Full overview — every block below plus `insights`             |
| GET    | `/api/v1/analytics/behavioral/snooze`                   | Snooze pattern + snooze-reduction rate                        |
| GET    | `/api/v1/analytics/behavioral/wake-consistency`         | Wake consistency, on-time rate, trend                         |
| GET    | `/api/v1/analytics/behavioral/verification-accuracy`    | Quality of wake-verification verdicts                         |
| GET    | `/api/v1/analytics/behavioral/sleep-adherence`          | Adherence to the preferred wake time                          |
| GET    | `/api/v1/analytics/behavioral/sleep-patterns`           | Recorded/estimated sleep nights, regularity, social jetlag    |
| GET    | `/api/v1/analytics/behavioral/productivity-correlation` | Behaviour ↔ outcome correlations                              |
| GET    | `/api/v1/analytics/behavioral/habits`                   | Habit score series and trend                                  |
| GET    | `/api/v1/analytics/behavioral/trends/weekly`            | Weekly trend series                                           |
| GET    | `/api/v1/analytics/behavioral/trends/monthly`           | Monthly trend series                                          |

### `POST /api/v1/analytics/events`

```json
{
  "event_type": "sleep.started",
  "entity_type": "user",
  "entity_id": 42,
  "event_data": { "at": "2026-08-12T22:40:00Z" },
  "occurred_at": "2026-08-12T22:40:03Z"
}
```

`event_type` must start with one of the allowed client prefixes — `alarm.`,
`challenge.`, `wake.`, `sleep.`, `profile.`, `habit.`, `recommendation.`, `ui.`
or `session.` — anything else is rejected with `400`. `sleep.started` /
`sleep.ended` are what the dashboard's *Log sleep* button emits, and
`event_data.at` backfills the true instant.

**`201 Created`**

```json
{
  "accepted": 1,
  "events": [{ "id": 9134, "event_type": "sleep.started", "created_at": "2026-08-12T22:40:03Z" }]
}
```

Batch ingest posts `{"events": [ ... ]}` with the same item shape.

---

## 9. Dashboard

| Method | Path                                      | Query                            | Description                                                 |
| ------ | ----------------------------------------- | -------------------------------- | ----------------------------------------------------------- |
| GET    | `/api/v1/dashboard/summary`               | `period` = `daily\|weekly\|monthly` | Single-call dashboard aggregate                          |
| GET    | `/api/v1/dashboard/wake-stats`            | `days`                           | Wake success, dismiss times, by hour/weekday                |
| GET    | `/api/v1/dashboard/challenge-performance` | `days`                           | Accuracy, points, completion rate, by type                  |
| GET    | `/api/v1/dashboard/productivity`          | `days`                           | Readiness/routine scores, improvement, sleep + correlations |
| GET    | `/api/v1/dashboard/alarm-history`         | `page`, `per_page`, `days`       | Paginated wake/snooze timeline                              |

`GET /dashboard/summary` defaults to `weekly`; a value outside
`daily|weekly|monthly` is rejected with `422`.

---

## 10. Recommendations, reports, notifications, coach, admin

### 10.1 Recommendations

| Method | Path                                                   | Description                          |
| ------ | ------------------------------------------------------ | ------------------------------------ |
| GET    | `/api/v1/recommendations`                              | Full feed (`category`, `limit`)      |
| GET    | `/api/v1/recommendations/daily`                        | Daily digest + plan                  |
| GET    | `/api/v1/recommendations/sleep`                        | Sleep-category feed + insights       |
| GET    | `/api/v1/recommendations/wake`                         | Wake-category feed + insights        |
| GET    | `/api/v1/recommendations/productivity`                 | Productivity-category feed + insights|
| PUT    | `/api/v1/recommendations/{recommendation_id}/feedback` | Rate a card                          |
| DELETE | `/api/v1/recommendations/{recommendation_id}/feedback` | Clear a rating (`204`)               |
| GET    | `/api/v1/recommendations/relevance`                    | Measured relevance (`days` optional) |

`PUT .../feedback` takes `{"rating": "helpful" | "not_helpful" | "dismissed"}`.
The id must exist in the caller's **current** feed (`404` otherwise); category,
priority and stated confidence are taken from the engine and are never trusted
from the client. Ratings replace each other — they never stack.
`relevance_rate = helpful / (helpful + not_helpful)`; dismissals are reported
but deliberately excluded from that ratio.

Feedback does not change what, or how, the engine recommends.

### 10.2 Reports

| Method | Path                                   | Description                                           |
| ------ | -------------------------------------- | ----------------------------------------------------- |
| GET    | `/api/v1/reports`                      | Available report types                                |
| GET    | `/api/v1/reports/{report_type}`        | JSON report (`days` **or** `start_date` + `end_date`) |
| GET    | `/api/v1/reports/{report_type}/export` | Download (`format=pdf` default, or `excel`)           |

`report_type` ∈ `habit`, `wake`, `challenge`, `productivity`, `sleep`. An
unknown type returns `400` listing the allowed values. Reports with no data
still return `200` with `"is_empty": true` and an `empty_message`.

Exports return `application/pdf` or
`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` with a
`Content-Disposition` attachment filename.

### 10.3 Notifications

| Method | Path                                 | Description                                                   |
| ------ | ------------------------------------ | ------------------------------------------------------------- |
| GET    | `/api/v1/notifications/`             | List (`page`, `per_page`, `notification_type`, `unread_only`) |
| GET    | `/api/v1/notifications/unread-count` | Unread badge count                                            |
| GET    | `/api/v1/notifications/pending`      | Scheduled but undelivered (`within_hours`, default 24)        |
| POST   | `/api/v1/notifications/mark-read`    | `{"notification_ids": [1, 2]}`                                |
| GET    | `/api/v1/notifications/preferences`  | Current preferences                                           |
| PUT    | `/api/v1/notifications/preferences`  | Update preferences — re-schedules immediately                 |
| POST   | `/api/v1/notifications/device-token` | Register an FCM token (`201`)                                 |
| DELETE | `/api/v1/notifications/device-token` | Unregister (`?fcm_token=...`)                                 |
| POST   | `/api/v1/notifications/test`         | Send a test notification                                      |

`PUT /notifications/preferences` accepts `notifications_enabled` (master
switch), the per-type toggles `bedtime_reminder_enabled`,
`wake_reminder_enabled`, `habit_alerts_enabled`, `challenge_reminders_enabled`,
`progress_updates_enabled` and `motivational_enabled`, their lead-time fields
(`bedtime_reminder_minutes_before` 5–120, `wake_reminder_minutes_before` 5–60),
`motivational_time`, `quiet_hours_start` / `quiet_hours_end`,
`notification_sound`, `notification_frequency`, `push_enabled` and
`email_notifications_enabled`.

`notification_frequency` gates which types may be enabled: `all` permits every
type, `essential` bedtime + wake only, `minimal` wake only. `alarm_trigger` and
`announcement` always deliver — they bypass quiet hours, the master switch and
the per-type toggles.

### 10.4 Wellness Coach

All routes require the `wellness_coach` or `admin` role, and every client route
is scoped to an **active** coach assignment (`404` otherwise). All accept `days`
(default `30`).

| Method | Path                                                      | Description                                                             |
| ------ | --------------------------------------------------------- | ----------------------------------------------------------------------- |
| GET    | `/api/v1/coach/overview`                                  | Roster KPIs, attention list, top clients                                |
| GET    | `/api/v1/coach/clients`                                   | Roster (`page`, `per_page`, `search`, `status`, `sort_by`, `sort_order`) |
| GET    | `/api/v1/coach/clients/{client_id}`                       | Client detail — profile + core metrics                                  |
| GET    | `/api/v1/coach/clients/{client_id}/behavioral`            | Snooze / wake / sleep / habit trends                                    |
| GET    | `/api/v1/coach/clients/{client_id}/habit-score`           | Habit score + breakdown + trend                                         |
| GET    | `/api/v1/coach/clients/{client_id}/wake-consistency`      | Wake consistency + snooze pattern                                       |
| GET    | `/api/v1/coach/clients/{client_id}/sleep-trends`          | Adherence + daily sleep series                                          |
| GET    | `/api/v1/coach/clients/{client_id}/challenge-performance` | Challenge accuracy, completion, recent attempts                         |
| GET    | `/api/v1/coach/clients/{client_id}/productivity`          | Productivity analytics                                                  |
| GET    | `/api/v1/coach/clients/{client_id}/recommendations`       | Full recommendation feed for that client                                |

`status` ∈ `all` (default), `needs_attention`, `on_track`, `inactive`.

### 10.5 Admin

All routes require the `admin` role. Analytics routes accept `days` **or**
`start_date` + `end_date`.

| Method | Path                                                | Description                                                                                  |
| ------ | --------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| GET    | `/api/v1/admin/dashboard`                           | Users, alarms, engagement, top performers                                                     |
| GET    | `/api/v1/admin/statistics`                          | Registration trend, activity by hour/weekday                                                  |
| GET    | `/api/v1/admin/analytics`                           | Platform analytics-event overview                                                             |
| GET    | `/api/v1/admin/alarms`                              | Cross-user alarm inventory and activity                                                       |
| GET    | `/api/v1/admin/recommendations`                     | Recommendation signal overview                                                                |
| GET    | `/api/v1/admin/reports`                             | System health + data-integrity audit                                                          |
| GET    | `/api/v1/admin/users`                               | Paginated users (`page`, `per_page`, `role`, `is_active`, `search`, `sort_by`, `sort_order`)  |
| GET    | `/api/v1/admin/users/{user_id}`                     | Deep user detail (`days`, default 30)                                                         |
| GET    | `/api/v1/admin/coach-assignments`                   | List assignments                                                                              |
| POST   | `/api/v1/admin/coach-assignments`                   | Assign a client to a coach (`201`)                                                            |
| DELETE | `/api/v1/admin/coach-assignments`                   | Remove an assignment (`?coach_id=&client_id=`, `204`)                                         |
| GET    | `/api/v1/admin/notification-settings`               | Platform channels, maintenance, alert thresholds                                              |
| PUT    | `/api/v1/admin/notification-settings`               | Update the above                                                                              |
| POST   | `/api/v1/admin/announcements/broadcast`             | Broadcast to all active users (`201`)                                                         |
| GET    | `/api/v1/admin/system-reports`                      | Available system report types                                                                 |
| GET    | `/api/v1/admin/system-reports/{report_type}`        | JSON system report                                                                            |
| GET    | `/api/v1/admin/system-reports/{report_type}/export` | PDF/Excel export                                                                              |

> ⚠️ `GET /admin/coach-assignments` has `is_active` defaulting to **`true`**.
> Omitting the parameter returns active rows only; pass `is_active=false`
> explicitly to read archived (soft-removed) assignments.

System `report_type` ∈ `user`, `alarm`, `habit`, `platform`.

---

## 11. Rate limiting

Rate limiting is applied to the authentication surface only
(`RATE_LIMIT_ENABLED`, default on). It is an in-process sliding window, so the
limits are per worker.

| Scope                       | Endpoints                                                                    | Limit | Window | Effect        |
| --------------------------- | ---------------------------------------------------------------------------- | ----: | -----: | ------------- |
| Per account (identifier)    | `/auth/login`, `/auth/token`                                                 |     5 |  300 s | 900 s lockout |
| Per caller address          | `/auth/login`, `/auth/token`                                                 |    20 |  300 s | 900 s lockout |
| Per account **and** address | `/auth/forgot-password`, `/auth/reset-password`, `/auth/resend-verification` |     3 |  900 s | 900 s cool-off |

Tunable via `LOGIN_MAX_ATTEMPTS`, `LOGIN_IP_MAX_ATTEMPTS`,
`LOGIN_ATTEMPT_WINDOW_SECONDS`, `LOGIN_LOCKOUT_SECONDS`,
`PASSWORD_RESET_MAX_REQUESTS` and `PASSWORD_RESET_WINDOW_SECONDS`.

A successful login clears the account's failure counter.

**`429 Too Many Requests`**

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 873
```

```json
{ "detail": "Too many failed login attempts. Try again in 873 seconds." }
```

No other endpoint is rate limited by the application. Request bodies are bounded
at the edge (`client_max_body_size 10m` in Nginx).

---

## 12. System and observability

| Method | Path                                | Auth                                          | Description                                        |
| ------ | ----------------------------------- | --------------------------------------------- | -------------------------------------------------- |
| GET    | `/api/v1/system/status`             | ❌ public                                      | Maintenance flag + message (drives the SPA banner) |
| POST   | `/api/v1/system/client-errors`      | ❌ public (own limiter)                        | Record a browser-side error (`202`)                |
| GET    | `/api/v1/system/metrics`            | 👑 admin                                       | Per-route p50/p95/p99 + challenge generation       |
| GET    | `/api/v1/system/metrics/prometheus` | 👑 admin **or** `Bearer METRICS_SCRAPE_TOKEN` | Prometheus text exposition                         |
| GET    | `/api/v1/system/alerts`             | 👑 admin                                       | Threshold alerts currently firing                  |
| GET    | `/api/v1/system/logging`            | 👑 admin                                       | Active logging configuration                       |

Plus the two unversioned probes:

| Method | Path      | Response                                                                                                                                                        |
| ------ | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GET    | `/`       | `{"name": "...", "version": "1.0.0", "description": "...", "docs": "/docs", "redoc": "/redoc"}` — the `docs`/`redoc` keys are omitted when the docs are disabled |
| GET    | `/health` | `{"status": "healthy", "version": "1.0.0"}`                                                                                                                      |

`/system/client-errors` is intentionally unauthenticated: a crash on the login
page must still be reportable. It has its own rate limiter, and the payload is
scrubbed before it reaches the log.

---

## 13. Maintenance mode

When an administrator enables maintenance mode
(`PUT /api/v1/admin/notification-settings`), every **mutating** request
(anything other than `GET`, `HEAD`, `OPTIONS`) from a non-admin is answered with:

```http
HTTP/1.1 503 Service Unavailable
```

```json
{ "detail": "<configured maintenance message>", "maintenance_mode": true }
```

Reads continue to work, admins bypass the block via the role claim in their
token, and `GET /api/v1/system/status` reports the flag so the SPA can show a
banner.

---

## 14. CORS

```python
CORSMiddleware(
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

| Setting           | Value                                                                                                      |
| ----------------- | ---------------------------------------------------------------------------------------------------------- |
| Allowed origins   | `CORS_ORIGINS` (default `["http://localhost:3000"]`), plus any `localhost` / `127.0.0.1` origin on any port |
| Allowed methods   | All                                                                                                        |
| Allowed headers   | All                                                                                                        |
| Allow credentials | `true` — required for the session cookies                                                                  |

In the Docker stack the SPA and the API share a single origin behind Nginx, so
`CORS_ORIGINS` is set to `PUBLIC_URL` and cross-origin requests are not needed.

---

## 15. Versioning

The API is versioned in the URL:

```
/api/v1/...     ← current
```

`GET /` reports the running application version. There is currently no `v2`, and
no deprecation headers are emitted.
