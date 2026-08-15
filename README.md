<p align="center">
  <img src="https://img.shields.io/badge/🧠_ICAP-Intelligent_Cognitive_Alarm_Platform-blueviolet?style=for-the-badge" alt="ICAP Banner"/>
</p>

<h1 align="center">🧠 Intelligent Cognitive Alarm Platform</h1>

<p align="center">
  <em>Wake up smarter. Challenge your mind. Own your mornings.</em>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.104+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"/></a>
  <a href="https://react.dev/"><img src="https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React"/></a>
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL"/></a>
  <a href="https://redis.io/"><img src="https://img.shields.io/badge/Redis-Cache-DC382D?style=flat-square&logo=redis&logoColor=white" alt="Redis"/></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker"/></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License"/></a>
</p>

---

## 📖 About

The **Intelligent Cognitive Alarm Platform (ICAP)** is a next-generation alarm system that goes beyond simple wake-up calls. It combines cognitive challenges, personalized difficulty scaling, and sleep analytics to help users build healthier morning routines and sharpen their minds from the moment they wake up.

Unlike traditional alarm apps, ICAP requires users to solve cognitive challenges — math problems, memory puzzles, pattern recognition tasks — before the alarm can be dismissed. The platform tracks wake behavior, adapts challenge difficulty over time, scores daily habits, and provides coaching recommendations on the dashboard.

The platform supports three roles — User, Wellness Coach, and Administrator — each with its own workspace, along with dedicated security, observability and reporting features.

> 👤 New here? Start with the **[User Guide](docs/USER_GUIDE.md)**.
> 📡 Integrating? See the **[API Reference](docs/api_documentation.md)**.

---

## 🏗️ Architecture Overview

ICAP follows a **modular monolith** architecture built with FastAPI, designed to evolve into microservices as the platform scales. The backend exposes a RESTful API consumed by the React web client (and future mobile clients).

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Layer                            │
│              (React SPA / Mobile App — future)               │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS
┌──────────────────────────▼──────────────────────────────────┐
│              Edge (Nginx — TLS, CSP/HSTS, static)            │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST
┌──────────────────────────▼──────────────────────────────────┐
│                       API Gateway                            │
│                   (FastAPI + Uvicorn)                        │
├──────────┬───────────┬───────────┬────────────┬─────────────┤
│  Auth    │  Alarm    │ Challenge │ Analytics  │ Recommend.  │
│ Module   │  Module   │  Module   │   Module   │   Module    │
├──────────┴───────────┴───────────┴────────────┴─────────────┤
│        APScheduler jobs (alarm dispatch, notifications,      │
│                 metric alerts, daily scheduling)             │
├──────────────────────────────────────────────────────────────┤
│                   Data Access Layer                          │
│              (SQLAlchemy ORM + Alembic)                      │
├──────────────────────────────┬──────────────────────────────┤
│     PostgreSQL / SQLite      │     Redis (rec. cache)       │
└──────────────────────────────┴──────────────────────────────┘
```

> For detailed architecture documentation, see [docs/architecture.md](docs/architecture.md).

---

## ✨ Features

### Milestone 1 — Project Setup, Auth, Profiles & Alarm Scheduling

- [x] **User Authentication** — Secure registration, login, and JWT sessions carried in HttpOnly cookies
- [x] **Session Revocation** — Logout and password reset invalidate outstanding access/refresh tokens server-side
- [x] **Brute-Force Protection** — Per-account and per-address login lockout plus password-reset rate limiting (HTTP 429 + `Retry-After`)
- [x] **User Profiles** — Customizable user profiles with cognitive preferences
- [x] **Password Security** — Bcrypt hashing with secure password policies
- [x] **Role-Based Access Control** — Admin and user roles with permission guards
- [x] **Input Validation** — Comprehensive Pydantic-based request validation
- [x] **Database Migrations** — Alembic-powered schema versioning
- [x] **API Documentation** — Auto-generated OpenAPI/Swagger docs
- [x] **Docker Support** — One-command development setup
- [x] **Health Checks** — Liveness and readiness endpoints
- [x] **CORS Configuration** — Configurable cross-origin resource sharing
- [x] **Alarm CRUD** — Create, update, toggle, and delete alarms
- [x] **Scheduling Engine** — Daily, weekday, weekend, one-time, and smart-adaptive schedules
- [x] **Snooze Policies** — Configurable snooze limits and intervals
- [x] **Challenge Linkage** — Per-alarm challenge type, count, and difficulty
- [x] **Difficulty Preferences** — Profile-level and per-alarm difficulty (`beginner` → `expert`)
- [x] **Server-Side Alarm Dispatch** — Scheduler pushes a ring notification even when no tab is open, and rolls over unattended alarms

### Milestone 2 — Cognitive Challenges & Wake-Up Verification

- [x] **Cognitive Challenge Engine** — Math, logic, memory, pattern, word, riddle, and quiz challenges
- [x] **AI Challenge Generation** — Google Gemini generates puzzles when `GEMINI_API_KEY` is set; procedural generators are the deterministic fallback and every challenge reports its `source` (`ai` / `procedural`)
- [x] **Wake-Up Verification** — Multi-step and consecutive-correct challenge cycles with a verification token required to dismiss
- [x] **Anti-Snooze Workflows** — `snooze_limit = 0` refuses snoozing; each snooze escalates the next challenge's difficulty
- [x] **Wake / Snooze Audit Logs** — Queryable wake and snooze event history
- [x] **Challenge Attempt Logs** — Clean, indexed attempt history with log-health audit

### Milestone 3 — Adaptive Intelligence, Habit Scoring & Recommendations

- [x] **Adaptive Difficulty** — Rule-based raise/lower from consecutive success/failure streaks
- [x] **Learning Pattern Analysis** — Mastery by challenge type, learning state, engagement level and its 14-day improvement
- [x] **Adaptation Effectiveness** — Measures whether difficulty changes actually moved the user toward the target accuracy band
- [x] **Analytics Ingestion** — Single and batch event ingest plus summary endpoints
- [x] **Behavioral Analytics** — Snooze patterns, wake consistency, sleep adherence, trends (pandas/numpy)
- [x] **Sleep Pattern Analytics** — Recorded (`sleep.started` / `sleep.ended`) sleep sessions preferred over estimates; regularity, social jetlag, sleep debt
- [x] **Behaviour ↔ Productivity Correlations** — Pearson/Spearman with a significance test, no SciPy dependency
- [x] **Habit Score** — Weighted formula: Wake Consistency 35% · Challenge Completion 25% · Snooze Reduction 20% · Sleep Adherence 20%
- [x] **Challenge Completion Rate** — Separate delivery ledger, so unanswered and timed-out challenges are counted (not just accuracy)
- [x] **Snooze Reduction Rate** — Snoozes per wake-up compared against the previous period
- [x] **Productivity Improvement Rate** — Period-over-period deltas for readiness, routine, accuracy and wakefulness
- [x] **Recommendation Engine** — Rule-based sleep, wake, habit, and productivity suggestions
- [x] **Recommendation Relevance** — Thumbs up/down/dismiss feedback, relevance rate and engine-confidence gap
- [x] **Redis Recommendation Cache** — Cached coaching results with TTL and invalidation
- [x] **React Dashboard** — Habit-score widget, recommendation cards, analytics views, preference settings

### Milestone 4 — Dashboards, Reports, Testing & Deployment

- [x] **Wellness Coach Workspace** — Roster KPIs, search/filter/sort, per-client behaviour, habit, sleep and challenge analytics
- [x] **Coach Assignment Management** — Admin UI and APIs to grant and revoke a coach's access to a client
- [x] **Admin Console** — User management, platform analytics, alarm/habit/recommendation overviews, system reports, announcements
- [x] **Maintenance Mode** — Blocks non-admin writes with `503` and shows a banner in the SPA
- [x] **Role-Based Routing** — Per-role navigation, guarded routes, Access Denied and 404 pages
- [x] **Notification Engine** — Bedtime, wake, habit, challenge, progress, motivational and announcement notifications with quiet hours, frequency tiers and FCM push
- [x] **Lifestyle Reports** — Habit, wake, challenge, productivity and sleep reports with PDF/Excel export

### Platform Engineering

- [x] **Structured Logging** — JSON logs, rotating files, per-request correlation id echoed as `X-Request-ID`
- [x] **Runtime Metrics & Alerting** — Per-route p50/p95/p99, `X-Process-Time`, threshold alerts, Prometheus exposition
- [x] **Security Hardening** — TLS + HSTS + CSP at the edge, OWASP test suite, dependency/SAST scanning in CI
- [x] **API Contract Testing** — Snapshot-based drift detection over all 132 routes, plus a coverage gate on the API surface
- [x] **Browser E2E** — Playwright journeys against a real backend + SPA

---

## 🛠️ Tech Stack

| Layer          | Technology                  | Purpose                          |
| -------------- | --------------------------- | -------------------------------- |
| **Backend**    | Python 3.11+ / FastAPI      | REST API & business logic        |
| **ORM**        | SQLAlchemy 2.0              | Database modeling & queries      |
| **Migrations** | Alembic                     | Schema versioning & migrations   |
| **Auth**       | python-jose / passlib       | JWT tokens & password hashing    |
| **Validation** | Pydantic v2                 | Request/response schemas         |
| **Database**   | PostgreSQL 16 / SQLite      | Primary data storage             |
| **Cache**      | Redis                       | Recommendation result caching    |
| **Scheduler**  | APScheduler                 | Alarm dispatch, notifications, alerts |
| **Analytics**  | pandas / numpy              | Behavioral analytics aggregates  |
| **AI**         | Google Gemini (optional)    | Challenge generation, with a procedural fallback |
| **Push**       | Firebase Cloud Messaging    | Web push notifications           |
| **Frontend**   | React 18 (CRA)              | Web client & dashboard           |
| **Edge**       | Nginx                       | TLS, security headers, static assets |
| **DevOps**     | Docker / Docker Compose     | Containerization & orchestration |
| **Testing**    | pytest / httpx / Jest / Playwright | Backend, frontend & browser E2E |
| **Docs**       | Swagger UI / ReDoc          | Interactive API documentation    |

---

## 🚀 Getting Started

### Prerequisites

- **Python** 3.11 or higher
- **Node.js** 18+ (for the React frontend)
- **PostgreSQL** 16 (or use Docker)
- **Redis** (optional — recommendations fall back to live compute if unavailable)
- **Docker & Docker Compose** (optional, recommended)
- **Git**

### Installation

#### 1. Clone the repository

```bash
git clone https://github.com/your-username/intelligent-cognitive-alarm-platform.git
cd intelligent-cognitive-alarm-platform
```

#### 2. Set up a virtual environment

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS/Linux)
source venv/bin/activate
```

#### 3. Install backend dependencies

```bash
cd backend
pip install -r requirements.txt
```

#### 4. Configure environment variables

```bash
# From the backend/ directory, copy the example environment file
cp .env.example .env

# Edit .env with your configuration
```

The defaults run against a local SQLite file (`backend/icap.db`), and Redis is
optional — if it is unreachable, recommendations are recomputed on each request.
No external services are required to start. See the
[Environment Variables](#-environment-variables) section for all available
options.

#### 5. Run database migrations

```bash
# Still in backend/
alembic upgrade head

# If the console script is not on your PATH (common on Windows), use:
python -m alembic upgrade head
```

#### 6. Start the development server

```bash
# Still in backend/
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`, with interactive docs at
`http://localhost:8000/docs`.

#### 7. Start the frontend (optional)

```bash
cd ../frontend
npm install
npm start
```

The web app will be available at `http://localhost:3000` and talks to
`http://localhost:8000/api/v1` by default. Override that with
`REACT_APP_API_URL` in `frontend/.env` if your API runs elsewhere.

### Running with Docker (Recommended)

```bash
# Configure required secrets and optional integrations
cp .env.example .env

# Set PUBLIC_URL to your public https:// origin (e.g. https://localhost for a
# local run) and fill in SECRET_KEY, POSTGRES_PASSWORD and REDIS_PASSWORD.

# Build and start PostgreSQL, Redis, backend, frontend, and Nginx
docker compose up --build -d
```

Open `https://localhost` (or your configured `PUBLIC_URL`). Only Nginx is
published to the host — PostgreSQL, Redis, the API and the frontend origin stay
on isolated Docker networks. Backend migrations run automatically before the API
starts.

The edge terminates TLS on `:8443` (published as `HTTPS_PORT`, default `443`)
and answers plain HTTP on `:8080` (`HTTP_PORT`, default `80`) with a `308`
redirect to HTTPS. If no certificate is mounted at `/etc/nginx/tls`, the
entrypoint generates a self-signed one for `TLS_COMMON_NAME`, so browsers will
warn until you mount a CA-issued certificate.

---

## 📡 API Endpoints

The API exposes **132 routes** under `/api/v1` (plus `GET /` and `GET /health`).
The tables below are a starting point; the full reference lives in
[docs/api_documentation.md](docs/api_documentation.md).

Authentication accepts **either** the HttpOnly session cookies set at login
**or** an `Authorization: Bearer <access_token>` header.

### Authentication

| Method | Endpoint                            | Description                             | Auth Required |
| ------ | ----------------------------------- | --------------------------------------- | ------------- |
| POST   | `/api/v1/auth/register`             | Register a new user (no tokens returned) | ❌             |
| POST   | `/api/v1/auth/login`                | Login (sets HttpOnly session cookies)    | ❌             |
| POST   | `/api/v1/auth/refresh`              | Refresh access token (cookie or body)    | 🔑            |
| POST   | `/api/v1/auth/logout`               | Revoke the current session               | 🔑            |
| POST   | `/api/v1/auth/logout-all`           | Revoke every session for the account     | 🔑            |
| POST   | `/api/v1/auth/verify-email`         | Verify an email address                  | ❌             |
| POST   | `/api/v1/auth/forgot-password`      | Request a password-reset link            | ❌             |
| POST   | `/api/v1/auth/reset-password`       | Set a new password from a reset token    | ❌             |
| GET    | `/api/v1/auth/oauth/google`         | Start Google sign-in (CSRF-protected)    | ❌             |

### Users & Profile

| Method | Endpoint                            | Description                    | Auth Required |
| ------ | ----------------------------------- | ------------------------------ | ------------- |
| GET    | `/api/v1/users/profile`             | Account + profile bundle       | 🔑            |
| PUT    | `/api/v1/users/profile`             | Update name, username, timezone| 🔑            |
| GET    | `/api/v1/users/profile/preferences` | Difficulty & habit prefs       | 🔑            |
| PUT    | `/api/v1/users/profile/preferences` | Update preferences             | 🔑            |
| GET    | `/api/v1/users/profile/stats`       | Stats including habit score    | 🔑            |
| GET    | `/api/v1/profiles/me`               | Full profile (adapted difficulty, lifetime counters) | 🔑 |
| GET    | `/api/v1/profiles/me/habit-score`   | Weighted habit score breakdown | 🔑            |

### Alarms & Challenges

| Method | Endpoint                              | Description                         | Auth Required |
| ------ | ------------------------------------- | ----------------------------------- | ------------- |
| GET    | `/api/v1/alarms/`                     | List alarms                         | 🔑            |
| POST   | `/api/v1/alarms/`                     | Create alarm                        | 🔑            |
| PUT    | `/api/v1/alarms/{id}`                 | Update alarm                        | 🔑            |
| PATCH  | `/api/v1/alarms/{id}/toggle`          | Enable / disable alarm              | 🔑            |
| GET    | `/api/v1/alarms/{id}/challenge`       | Get the active challenge            | 🔑            |
| POST   | `/api/v1/alarms/{id}/verify`          | Verify a challenge answer           | 🔑            |
| POST   | `/api/v1/alarms/{id}/dismiss`         | Verified dismiss                    | 🔑            |
| POST   | `/api/v1/alarms/{id}/snooze`          | Snooze alarm                        | 🔑            |
| POST   | `/api/v1/alarms/{id}/fail-wake`       | Abandon the wake cycle              | 🔑            |
| POST   | `/api/v1/alarms/challenge/practice`   | Start a practice challenge          | 🔑            |
| GET    | `/api/v1/alarms/challenge/history`    | Challenge attempt history           | 🔑            |
| GET    | `/api/v1/alarms/challenge/log-health` | Attempt-log cleanliness audit       | 🔑            |

### Dashboard, Analytics & Recommendations

| Method | Endpoint                                | Description                      | Auth Required |
| ------ | --------------------------------------- | -------------------------------- | ------------- |
| GET    | `/api/v1/dashboard/summary`             | Single-call dashboard aggregate  | 🔑            |
| GET    | `/api/v1/dashboard/productivity`        | Readiness, sleep and correlations| 🔑            |
| POST   | `/api/v1/analytics/events`              | Ingest a single analytics event  | 🔑            |
| POST   | `/api/v1/analytics/events/batch`        | Ingest a batch of events         | 🔑            |
| GET    | `/api/v1/analytics/behavioral`          | Behavioral analytics overview    | 🔑            |
| GET    | `/api/v1/recommendations`               | All coaching recommendations     | 🔑            |
| GET    | `/api/v1/recommendations/daily`         | Daily digest for the dashboard   | 🔑            |
| PUT    | `/api/v1/recommendations/{id}/feedback` | Rate a recommendation            | 🔑            |
| GET    | `/api/v1/reports/{report_type}/export`  | Download a PDF/Excel report      | 🔑            |

### Notifications, Coaching & Administration

| Method | Endpoint                              | Description                       | Auth Required |
| ------ | ------------------------------------- | --------------------------------- | ------------- |
| GET    | `/api/v1/notifications/`              | List notifications                | 🔑            |
| PUT    | `/api/v1/notifications/preferences`   | Update notification preferences   | 🔑            |
| POST   | `/api/v1/notifications/device-token`  | Register an FCM device token      | 🔑            |
| GET    | `/api/v1/coach/overview`              | Roster KPIs                       | 🎯 Coach      |
| GET    | `/api/v1/coach/clients`               | Assigned clients                  | 🎯 Coach      |
| GET    | `/api/v1/admin/dashboard`             | Platform dashboard                | 👑 Admin      |
| GET    | `/api/v1/admin/users`                 | Paginated user management         | 👑 Admin      |
| POST   | `/api/v1/admin/coach-assignments`     | Assign a client to a coach        | 👑 Admin      |
| PUT    | `/api/v1/admin/notification-settings` | Channels, maintenance, thresholds | 👑 Admin      |

### System & Health

| Method | Endpoint                       | Description                          | Auth Required |
| ------ | ------------------------------ | ------------------------------------ | ------------- |
| GET    | `/health`                      | Health check                         | ❌             |
| GET    | `/`                            | Root / API information               | ❌             |
| GET    | `/api/v1/system/status`        | Maintenance flag for the SPA banner  | ❌             |
| GET    | `/api/v1/system/metrics`       | Measured per-route response times    | 👑 Admin      |
| GET    | `/api/v1/system/alerts`        | Threshold alerts currently firing    | 👑 Admin      |

> 📚 Interactive docs at `http://localhost:8000/docs` (Swagger UI) or
> `http://localhost:8000/redoc` (ReDoc). These are **disabled when
> `ENVIRONMENT=production`** — set `ENABLE_API_DOCS=true` to re-enable them.

---

## 📖 Documentation

| Document                                                     | What it covers                                                        |
| ------------------------------------------------------------ | --------------------------------------------------------------------- |
| [User Guide](docs/USER_GUIDE.md)                              | Every product flow for users, wellness coaches and administrators      |
| [API Reference](docs/api_documentation.md)                    | Auth, conventions, all 132 routes, rate limits, errors                 |
| [Architecture](docs/architecture.md)                          | System design and module boundaries                                    |
| [Database Design](docs/database_design.md)                    | Schema and relationships                                               |
| [Authentication Flow](docs/AUTHENTICATION_FLOW.md)            | Login, refresh, OAuth and session revocation                           |
| [Performance](docs/PERFORMANCE.md)                            | Measured latency and capacity results                                  |
| [Security Review](docs/SECURITY_REVIEW.md)                    | Findings, fixes and the advisory register                              |
| [RBAC Checklist](docs/SECURITY_RBAC_CHECKLIST.md)             | Role/permission verification matrix                                    |
| [QA Bug Report](docs/QA_BUG_REPORT.md)                        | QA findings and their resolutions                                      |
| [Mobile App Spec](docs/MOBILE_APP_SPEC.md)                    | Phase A plan for the Android React Native client (not yet implemented) |

---

## 📁 Project Structure

```
intelligent-cognitive-alarm-platform/
├── backend/
│   ├── alembic/                    # Database migrations
│   │   ├── versions/               # Migration scripts (baseline → head)
│   │   ├── env.py                  # Alembic environment config
│   │   └── script.py.mako          # Migration template
│   ├── app/
│   │   ├── api/
│   │   │   ├── deps.py             # Auth / role dependencies
│   │   │   └── v1/
│   │   │       ├── endpoints/      # auth, users, profiles, alarms, analytics,
│   │   │       │                   # dashboard, recommendations, reports,
│   │   │       │                   # notifications, coach, admin, system
│   │   │       └── router.py       # API router aggregation
│   │   ├── core/
│   │   │   ├── config.py           # App configuration
│   │   │   ├── security.py         # JWT & password utils
│   │   │   ├── cookies.py          # HttpOnly session cookies
│   │   │   ├── oauth_state.py      # OAuth2 anti-CSRF state
│   │   │   ├── rate_limit.py       # Login / reset rate limiting
│   │   │   ├── logging_config.py   # Structured JSON logging
│   │   │   ├── request_metrics.py  # Per-route latency reservoir
│   │   │   ├── request_context.py  # Correlation ids
│   │   │   └── redis_client.py     # Redis client (soft-fail)
│   │   ├── db/                     # Session & engine
│   │   ├── middleware/             # Request-context middleware
│   │   ├── models/                 # SQLAlchemy models
│   │   ├── schemas/                # Pydantic request/response models
│   │   ├── services/               # Business logic
│   │   │   ├── habit_score.py
│   │   │   ├── challenge_service.py
│   │   │   ├── ai_challenge_provider.py
│   │   │   ├── alarm_dispatch_service.py
│   │   │   ├── behavioral_analytics_service.py
│   │   │   ├── recommendation_service.py
│   │   │   ├── notification_service.py
│   │   │   ├── report_service.py
│   │   │   └── coach_service.py
│   │   └── main.py                 # FastAPI app entry point
│   ├── perf/                       # Performance harness & load tests
│   ├── scripts/                    # E2E backend runner, QA helpers
│   ├── tests/                      # Backend test suite
│   ├── .coveragerc                 # Coverage config for the API surface
│   ├── alembic.ini                 # Alembic configuration
│   ├── bandit.yaml                 # SAST configuration
│   ├── Dockerfile                  # Backend container
│   └── requirements.txt            # Python dependencies
├── frontend/                       # React SPA
│   ├── e2e/                        # Playwright journeys
│   ├── src/
│   │   ├── pages/                  # Dashboard, Alarms, Practice, Analytics,
│   │   │                           # Recommendations, Reports, Profile,
│   │   │                           # Wellness Coach, Admin, auth pages
│   │   ├── components/             # Layout, active alarm modal, panels
│   │   ├── hooks/                  # Data hooks (e.g. useCoachDashboard)
│   │   ├── services/               # API client, analytics, error reporting
│   │   ├── store/                  # Zustand stores
│   │   └── utils/                  # Route access, time formatting
│   ├── playwright.config.js
│   └── package.json
├── nginx/                          # Edge: TLS, CSP/HSTS, static delivery
├── scripts/
│   └── security_scan.py            # pip-audit + bandit + npm audit
├── docs/
│   ├── USER_GUIDE.md               # End-user, coach and admin guide
│   ├── api_documentation.md        # API reference
│   ├── architecture.md             # Architecture documentation
│   ├── database_design.md          # Database schema design
│   ├── AUTHENTICATION_FLOW.md      # Auth & session flows
│   ├── PERFORMANCE.md              # Measured performance results
│   ├── SECURITY_REVIEW.md          # Security findings & advisory register
│   ├── SECURITY_RBAC_CHECKLIST.md  # RBAC verification checklist
│   ├── MILESTONE_3_CLOSEOUT.md     # M3 demo & audit checklist (historical)
│   └── QA_BUG_REPORT.md            # QA findings
├── .github/workflows/              # tests, security, performance & container pipelines
├── docker-compose.yml              # Multi-container orchestration
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🔐 Environment Variables

The tables below cover the variables you are most likely to set. The complete
templates are `.env.example` (Docker stack) and `backend/.env.example` (local
backend); `frontend/.env.example` covers the browser build.

### Core

| Variable                      | Description                                     | Default                     | Required |
| ----------------------------- | ----------------------------------------------- | --------------------------- | -------- |
| `ENVIRONMENT`                 | `development` \| `test` \| `production`         | `development`               | No       |
| `SECRET_KEY`                  | JWT signing secret. Production requires ≥ 32 non-placeholder characters | — | Production |
| `DATABASE_URL`                | SQLAlchemy connection string                    | `sqlite:///./icap.db`       | Local    |
| `ALGORITHM`                   | JWT algorithm                                   | `HS256`                     | No       |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime (minutes)                 | `30`                        | No       |
| `REFRESH_TOKEN_EXPIRE_DAYS`   | Refresh token lifetime (days)                   | `7`                         | No       |
| `CORS_ORIGINS`                | Allowed CORS origins (JSON list)                | `["http://localhost:3000"]` | No       |
| `FRONTEND_URL`                | SPA base URL used by auth/email redirects       | `http://localhost:3000`     | No       |
| `ENABLE_API_DOCS`             | Serve `/docs`, `/redoc`, `/openapi.json`        | on except in production     | No       |
| `INITIAL_ADMIN_EMAIL`         | Optional first-run admin email                  | —                           | No       |
| `INITIAL_ADMIN_PASSWORD`      | Optional first-run admin password               | —                           | No       |

### Session cookies & abuse protection

| Variable                       | Description                                | Default              |
| ------------------------------ | ------------------------------------------ | -------------------- |
| `AUTH_COOKIE_ENABLED`          | Issue HttpOnly session cookies              | `true`               |
| `ACCESS_COOKIE_NAME`           | Access-token cookie name                    | `icap_access_token`  |
| `REFRESH_COOKIE_NAME`          | Refresh-token cookie name                   | `icap_refresh_token` |
| `AUTH_COOKIE_SECURE`           | Force `Secure`; mandatory in production      | derived from `ENVIRONMENT` |
| `AUTH_COOKIE_SAMESITE`         | Cookie `SameSite` policy                    | `lax`                |
| `RATE_LIMIT_ENABLED`           | Login / password-reset limiting              | `true`               |
| `LOGIN_MAX_ATTEMPTS`           | Failed logins per account before lockout     | `5`                  |
| `LOGIN_IP_MAX_ATTEMPTS`        | Failed logins per caller address             | `20`                 |
| `LOGIN_LOCKOUT_SECONDS`        | Lockout duration                             | `900`                |
| `PASSWORD_RESET_MAX_REQUESTS`  | Reset/verification emails per window         | `3`                  |

### Docker edge & data services

| Variable            | Description                                                | Default            |
| ------------------- | ---------------------------------------------------------- | ------------------ |
| `PUBLIC_URL`        | Public origin. **Use your `https://` origin** — the edge redirects HTTP to HTTPS | `https://localhost` (compose fallback) |
| `HTTP_PORT`         | Host port mapped to Nginx `:8080` (redirects to HTTPS)      | `80`               |
| `HTTPS_PORT`        | Host port mapped to Nginx `:8443` (TLS)                     | `443`              |
| `TLS_COMMON_NAME`   | CN/SAN of the fallback self-signed certificate              | `localhost`        |
| `CDN_BASE_URL`      | CDN origin for hashed `/static` assets (build-time)         | — (same-origin)    |
| `POSTGRES_DB`       | PostgreSQL database name                                    | `icap_db`          |
| `POSTGRES_USER`     | PostgreSQL user                                             | `icap_user`        |
| `POSTGRES_PASSWORD` | PostgreSQL password (URL-safe)                              | — (required)       |
| `REDIS_PASSWORD`    | Redis password (URL-safe)                                   | — (required)       |
| `REDIS_ENABLED`     | Enable the Redis recommendation cache                       | `true`             |
| `REDIS_URL`         | Redis connection URL                                        | `redis://localhost:6379/0` |
| `RECOMMENDATION_CACHE_TTL_SECONDS` | Recommendation cache TTL                     | `300`              |

### Integrations, scheduling & observability

| Variable                         | Description                                              | Default              |
| -------------------------------- | -------------------------------------------------------- | -------------------- |
| `SMTP_HOST` / `SMTP_*`           | Outbound email. When unset, verification and reset links are written to the log instead | — |
| `OAUTH2_GOOGLE_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | Google sign-in                    | —                    |
| `GEMINI_API_KEY`                 | Enables AI-generated challenges                           | —                    |
| `AI_CHALLENGE_ENABLED`           | Master switch for AI generation                           | `true`               |
| `FCM_ENABLED`                    | Firebase Cloud Messaging push delivery                    | `false` (compose)    |
| `FIREBASE_CREDENTIALS_JSON`      | Base64 service-account JSON (private server credential)   | —                    |
| `ALARM_DISPATCH_ENABLED`         | Server-side alarm ring dispatch                           | `true`               |
| `ALARM_DISPATCH_INTERVAL_SECONDS`| Due-alarm sweep cadence                                   | `20`                 |
| `NOTIFICATION_PROCESSING_INTERVAL_SECONDS` | Notification queue drain cadence                | `60`                 |
| `LOG_LEVEL` / `LOG_FORMAT`       | `INFO` and `json` \| `console`                            | `INFO` / `json`      |
| `LOG_TO_FILE` / `LOG_DIR`        | Rotating file logging (degrades to stdout if unwritable)  | `true` / `logs`      |
| `LOG_TO_CONSOLE`                 | stdout logging; `false` keeps the dev terminal quiet      | `true`               |
| `METRICS_ALERTS_ENABLED`         | Evaluate threshold alerts on measured metrics             | `true`               |
| `METRICS_ALERT_P95_MS`           | p95 latency alert threshold                               | `400`                |
| `METRICS_ALERT_WEBHOOK_URL`      | Optional outbound alert webhook                           | —                    |
| `METRICS_SCRAPE_TOKEN`           | Bearer token for `/system/metrics/prometheus`             | — (admins only)      |

Browser Firebase values (`REACT_APP_FIREBASE_*`) are build arguments and are
public identifiers. `FIREBASE_CREDENTIALS_JSON` is a private server credential —
use base64 and never a browser key.

---

## 🐳 Docker

### Production stack

```bash
# One-command build and startup
docker compose up --build -d

# Verify health and view logs
docker compose ps
docker compose logs -f nginx backend

# Access the database
docker compose exec postgres psql -U icap_user -d icap_db

# Shut everything down
docker compose down

# Also delete PostgreSQL, Redis, log and certificate volumes
docker compose down -v
```

Hardening applied by the stack: containers run with `no-new-privileges` and a
read-only root filesystem, the API's rotated logs live on a named volume, and
Nginx serves TLS 1.2/1.3 only with HSTS, a `script-src 'self'` CSP,
`X-Frame-Options: DENY` and a `404` for the API documentation routes.

For an internet-facing deployment, mount a CA-issued certificate over
`/etc/nginx/tls` (or terminate TLS at a load balancer in front of `:8443`) and
set `PUBLIC_URL` plus `OAUTH2_GOOGLE_REDIRECT_URI` to the resulting HTTPS URLs.

---

## 🧪 Testing

```bash
# Run all backend tests
cd backend
pytest

# Run with verbose output
pytest -v

# Run with coverage (config lives in backend/.coveragerc — it scopes the gate to
# app/api + app/schemas and fails under 85%)
pytest --cov --cov-report=html

# Run specific test file
pytest tests/test_auth.py

# Run tests matching a pattern
pytest -k "test_login"

# API contract + inventory suite (regenerate the snapshot after adding a route:
# ICAP_UPDATE_API_SNAPSHOT=1 pytest tests/test_api_contract.py)
pytest tests/test_api_contract.py tests/test_qa_api_inventory.py -q

# Security suite (OWASP Top 10 coverage)
pytest tests/test_security_owasp.py -q
```

Open `htmlcov/index.html` to view the coverage report in your browser.

> The TLS edge tests (`tests/test_tls_runtime.py`) build and run the real Nginx
> image. They **skip** when Docker is unavailable, or when
> `ICAP_SKIP_EDGE_TESTS=1` is set.

```bash
# Frontend unit tests
cd frontend
npm test -- --watchAll=false

# Browser end-to-end journeys (starts a real backend + SPA)
npm run test:e2e:install   # one-time: download the Chromium build
npm run test:e2e
npm run test:e2e:report
```

```bash
# Dependency + static analysis (pip-audit, bandit, npm audit — one exit code)
python scripts/security_scan.py
```

### Performance

```bash
# Enforce the frontend bundle budget (needs a production build first)
cd frontend
npm run build
npm run check:bundle-size
node scripts/precompress.js --verify

# Backend performance regression suites
cd backend
pytest tests/test_asset_delivery.py tests/test_dashboard_performance.py \
  tests/test_aggregate_cache.py tests/test_api_latency.py \
  tests/test_challenge_generation_latency.py \
  tests/test_concurrency_capacity.py -q
```

All of the above run automatically via `.github/workflows/performance.yml`,
which additionally runs a capacity ramp against a live server backed by real
PostgreSQL. Dependency scanning and the TLS edge job run via
`.github/workflows/security.yml`. Harness usage is in
[`backend/perf/README.md`](backend/perf/README.md); measured results are in
[`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

### Continuous integration

| Workflow | What it runs |
|---|---|
| `tests.yml` | Full backend suite with the coverage gate, frontend unit tests + production build, and the Playwright journeys. |
| `security.yml` | OWASP suite, dependency/SAST scanning, and the TLS edge job against a real Nginx container. |
| `performance.yml` | Bundle budget, backend performance guards, and a PostgreSQL-backed capacity ramp. |
| `containers.yml` | Builds every image and smoke-tests the running stack through the edge. |

---

## 🗺️ Milestone Roadmap

| Milestone   | Focus Area                              | Status         |
| ----------- | --------------------------------------- | -------------- |
| **M1** 🔐   | Week 1–2 — Project Setup, Auth, Profiles & Alarm Scheduling | 🟢 Completed |
| **M2** 🧩   | Week 3–4 — Cognitive Challenges & Wake-Up Verification | 🟢 Completed |
| **M3** 🎯   | Week 5–6 — Adaptive Intelligence, Habit Scoring & Recommendations | 🟢 Completed |
| **M4** 🚀   | Week 7–8 — Dashboards, Reports, Testing & Deployment | 🟡 In progress — hardened Docker/TLS stack and CI pipelines; cloud deployment artifacts and horizontal scaling are not in the repo |

**Known gaps.** These are deliberate and tracked, not silent omissions:

- No React Native / mobile client; the SPA is not an installable PWA and has no
  offline mode (the only service worker handles FCM push).
- Adaptation and recommendations are **rule-based** — there is no trained ML
  model in the repository.
- Rate limiting and the metrics reservoirs are **in-process**, so they are
  per-worker rather than cluster-wide.
- No cloud (AWS/Azure) deployment manifests.

> Milestone 3 demo notes and attempt-log audit steps:
> [docs/MILESTONE_3_CLOSEOUT.md](docs/MILESTONE_3_CLOSEOUT.md) (historical
> record, dated 2026-07-20).

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'feat: add amazing feature'`)
4. **Push** to your branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### Commit Convention

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix     | Use Case                    |
| ---------- | --------------------------- |
| `feat:`    | New feature                 |
| `fix:`     | Bug fix                     |
| `docs:`    | Documentation changes       |
| `refactor:`| Code refactoring            |
| `test:`    | Adding/updating tests       |
| `chore:`   | Maintenance tasks           |

### Code Style

- Follow **PEP 8** for Python code
- Use **type hints** for all function signatures
- Write **docstrings** for all public functions and classes
- Keep API-surface coverage above the **85%** gate in `backend/.coveragerc`
- Regenerate `backend/tests/api_contract_snapshot.json` when you add or change a
  route (`ICAP_UPDATE_API_SNAPSHOT=1 pytest tests/test_api_contract.py`)

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  Built with ❤️ by <strong>Krithik Ananth</strong>
</p>

<p align="center">
  <a href="#-intelligent-cognitive-alarm-platform">⬆ Back to Top</a>
</p>
