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
  <img src="https://img.shields.io/badge/Status-Milestone_3_Complete-brightgreen?style=flat-square" alt="Status"/>
</p>

---

## 📖 About

The **Intelligent Cognitive Alarm Platform (ICAP)** is a next-generation alarm system that goes beyond simple wake-up calls. It combines cognitive challenges, personalized difficulty scaling, and sleep analytics to help users build healthier morning routines and sharpen their minds from the moment they wake up.

Unlike traditional alarm apps, ICAP requires users to solve cognitive challenges — math problems, memory puzzles, pattern recognition tasks — before the alarm can be dismissed. The platform tracks wake behavior, adapts challenge difficulty over time, scores daily habits, and surfaces coaching recommendations on the dashboard.

---

## 🏗️ Architecture Overview

ICAP follows a **modular monolith** architecture built with FastAPI, designed to evolve into microservices as the platform scales. The backend exposes a RESTful API consumed by the React web client (and future mobile clients).

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Layer                            │
│              (React SPA / Mobile App — future)               │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS / REST
┌──────────────────────────▼──────────────────────────────────┐
│                       API Gateway                            │
│                   (FastAPI + Uvicorn)                        │
├──────────┬───────────┬───────────┬────────────┬─────────────┤
│  Auth    │  Alarm    │ Challenge │ Analytics  │ Recommend.  │
│ Service  │  Service  │  Engine   │  Engine    │  Engine     │
├──────────┴───────────┴───────────┴────────────┴─────────────┤
│                   Data Access Layer                          │
│              (SQLAlchemy ORM + Alembic)                      │
├──────────────────────────────┬──────────────────────────────┤
│     PostgreSQL / SQLite      │     Redis (rec. cache)       │
└──────────────────────────────┴──────────────────────────────┘
```

> For detailed architecture documentation, see [docs/architecture.md](docs/architecture.md).

---

## ✨ Features

### Milestone 1 — Auth, Users & Foundation

- [x] **User Authentication** — Secure registration, login, and JWT-based session management
- [x] **User Profiles** — Customizable user profiles with cognitive preferences
- [x] **Password Security** — Bcrypt hashing with secure password policies
- [x] **Role-Based Access Control** — Admin and user roles with permission guards
- [x] **Input Validation** — Comprehensive Pydantic-based request validation
- [x] **Database Migrations** — Alembic-powered schema versioning
- [x] **API Documentation** — Auto-generated OpenAPI/Swagger docs
- [x] **Docker Support** — One-command development setup
- [x] **Health Checks** — Liveness and readiness endpoints
- [x] **CORS Configuration** — Configurable cross-origin resource sharing

### Milestone 2 — Alarms, Scheduling & Attempt Logging

- [x] **Alarm CRUD** — Create, update, toggle, and delete alarms
- [x] **Scheduling Engine** — Daily, weekday, weekend, one-time, and smart-adaptive schedules
- [x] **Snooze Policies** — Configurable snooze limits and intervals
- [x] **Challenge Linkage** — Per-alarm challenge type, count, and difficulty
- [x] **Wake / Snooze Audit Logs** — Queryable wake and snooze event history
- [x] **Challenge Attempt Logs** — Clean, indexed attempt history with log-health audit

### Milestone 3 — Challenges, Habit Score & Recommendations

- [x] **Cognitive Challenge Engine** — Math, logic, memory, pattern, word, riddle, and quiz challenges
- [x] **Difficulty Preferences** — Profile-level and per-alarm difficulty (`beginner` → `expert`)
- [x] **Adaptive Difficulty** — Rule-based raise/lower from consecutive success/failure streaks
- [x] **Analytics Ingestion** — Single and batch event ingest plus summary endpoints
- [x] **Behavioral Analytics** — Snooze patterns, wake consistency, sleep adherence, trends (pandas/numpy)
- [x] **Habit Score** — Weighted formula: Wake Consistency 35% · Challenge Completion 25% · Snooze Reduction 20% · Sleep Adherence 20%
- [x] **Recommendation Engine** — Rule-based sleep, wake, habit, and productivity suggestions
- [x] **Redis Recommendation Cache** — Cached coaching results with TTL and invalidation
- [x] **React Dashboard** — Habit-score widget, recommendation cards, analytics views, preference settings

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
| **Analytics**  | pandas / numpy              | Behavioral analytics aggregates  |
| **Frontend**   | React 18 (CRA)              | Web client & dashboard           |
| **DevOps**     | Docker / Docker Compose     | Containerization & orchestration |
| **Testing**    | pytest / httpx / Jest       | Backend & frontend testing       |
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
# Copy the example environment file
cp .env.example .env

# Edit .env with your configuration
```

See the [Environment Variables](#-environment-variables) section for all available options.

#### 5. Run database migrations

```bash
cd backend
alembic upgrade head
```

#### 6. Start the development server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.

#### 7. Start the frontend (optional)

```bash
cd frontend
npm install
npm start
```

The web app will be available at `http://localhost:3000`.

### Running with Docker (Recommended)

```bash
# Start all services (db + redis + backend)
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

> Docker Compose runs the database, Redis, and backend. Start the React frontend separately with `npm start` in `frontend/`.

---

## 📡 API Endpoints

### Authentication

| Method | Endpoint                | Description            | Auth Required |
| ------ | ----------------------- | ---------------------- | ------------- |
| POST   | `/api/v1/auth/register` | Register a new user    | ❌             |
| POST   | `/api/v1/auth/login`    | Login & get JWT tokens | ❌             |
| POST   | `/api/v1/auth/refresh`  | Refresh access token   | 🔑             |
| POST   | `/api/v1/auth/logout`   | Invalidate tokens      | 🔑             |

### Users & Profile

| Method | Endpoint                           | Description                    | Auth Required |
| ------ | ---------------------------------- | ------------------------------ | ------------- |
| GET    | `/api/v1/users/profile`            | Get current user profile       | 🔑             |
| PUT    | `/api/v1/users/profile`            | Update current user            | 🔑             |
| GET    | `/api/v1/users/profile/preferences`| Get difficulty & habit prefs   | 🔑             |
| PUT    | `/api/v1/users/profile/preferences`| Update preferences             | 🔑             |
| GET    | `/api/v1/users/profile/stats`      | Stats including habit score    | 🔑             |
| GET    | `/api/v1/profiles/me`              | Profile + habit score attach   | 🔑             |
| GET    | `/api/v1/profiles/me/habit-score`  | Weighted habit score breakdown | 🔑             |

### Alarms & Challenges

| Method | Endpoint                              | Description                         | Auth Required |
| ------ | ------------------------------------- | ----------------------------------- | ------------- |
| GET    | `/api/v1/alarms/`                     | List alarms                         | 🔑             |
| POST   | `/api/v1/alarms/`                     | Create alarm                        | 🔑             |
| PUT    | `/api/v1/alarms/{id}`                 | Update alarm                        | 🔑             |
| POST   | `/api/v1/alarms/{id}/snooze`          | Snooze alarm                        | 🔑             |
| POST   | `/api/v1/alarms/{id}/dismiss`         | Verified dismiss                    | 🔑             |
| GET    | `/api/v1/alarms/{id}/challenge`       | Get active challenge                | 🔑             |
| POST   | `/api/v1/alarms/{id}/verify`          | Verify challenge answer             | 🔑             |
| GET    | `/api/v1/alarms/challenge/history`    | Challenge attempt history           | 🔑             |
| GET    | `/api/v1/alarms/challenge/log-health` | Attempt-log cleanliness audit       | 🔑             |

### Analytics & Recommendations

| Method | Endpoint                          | Description                      | Auth Required |
| ------ | --------------------------------- | -------------------------------- | ------------- |
| POST   | `/api/v1/analytics/events`        | Ingest a single analytics event  | 🔑             |
| POST   | `/api/v1/analytics/events/batch`  | Ingest a batch of events         | 🔑             |
| GET    | `/api/v1/analytics/behavioral`    | Behavioral analytics overview    | 🔑             |
| GET    | `/api/v1/recommendations`         | All coaching recommendations     | 🔑             |
| GET    | `/api/v1/recommendations/daily`   | Daily digest for the dashboard   | 🔑             |

### Health

| Method | Endpoint | Description            | Auth Required |
| ------ | -------- | ---------------------- | ------------- |
| GET    | `/health`| Health check           | ❌             |
| GET    | `/`      | Root / welcome message | ❌             |

> 📚 Full API documentation available at `http://localhost:8000/docs` (Swagger UI) or `http://localhost:8000/redoc` (ReDoc).

---

## 📁 Project Structure

```
intelligent-cognitive-alarm-platform/
├── backend/
│   ├── alembic/                    # Database migrations
│   │   ├── versions/               # Migration scripts
│   │   ├── env.py                  # Alembic environment config
│   │   └── script.py.mako          # Migration template
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── endpoints/      # Route handlers
│   │   │       │   ├── auth.py
│   │   │       │   ├── users.py
│   │   │       │   ├── profiles.py
│   │   │       │   ├── alarms.py
│   │   │       │   ├── analytics.py
│   │   │       │   ├── recommendations.py
│   │   │       │   └── admin.py
│   │   │       └── router.py       # API router aggregation
│   │   ├── core/
│   │   │   ├── config.py           # App configuration
│   │   │   ├── security.py         # JWT & password utils
│   │   │   ├── redis_client.py     # Redis client (soft-fail)
│   │   │   └── database.py         # Database connection
│   │   ├── models/                 # SQLAlchemy models
│   │   ├── schemas/                # Pydantic schemas
│   │   ├── services/               # Business logic
│   │   │   ├── habit_score.py
│   │   │   ├── challenge_service.py
│   │   │   ├── behavioral_analytics_service.py
│   │   │   ├── recommendation_service.py
│   │   │   ├── recommendation_cache.py
│   │   │   └── attempt_log_service.py
│   │   └── main.py                 # FastAPI app entry point
│   ├── tests/                      # Backend test suite
│   ├── alembic.ini                 # Alembic configuration
│   ├── Dockerfile                  # Backend container
│   └── requirements.txt            # Python dependencies
├── frontend/                       # React SPA (dashboard & alarms)
│   ├── src/
│   │   ├── pages/                  # Dashboard, Alarms, Analytics, Profile
│   │   ├── components/
│   │   ├── services/               # API client & analytics tracker
│   │   └── store/                  # Zustand stores
│   └── package.json
├── docs/
│   ├── architecture.md             # Architecture documentation
│   ├── database_design.md          # Database schema design
│   ├── api_documentation.md        # API reference
│   ├── MILESTONE_3_CLOSEOUT.md     # M3 demo & audit checklist
│   └── QA_BUG_REPORT.md            # QA findings
├── docker-compose.yml              # Multi-container orchestration
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🔐 Environment Variables

| Variable                         | Description                         | Default                     | Required |
| -------------------------------- | ----------------------------------- | --------------------------- | -------- |
| `DATABASE_URL`                   | PostgreSQL connection string        | `sqlite:///./icap.db`       | Yes      |
| `SECRET_KEY`                     | JWT signing secret                  | —                           | Yes      |
| `ALGORITHM`                      | JWT algorithm                       | `HS256`                     | No       |
| `ACCESS_TOKEN_EXPIRE_MINUTES`    | Access token lifetime (mins)        | `30`                        | No       |
| `REFRESH_TOKEN_EXPIRE_DAYS`      | Refresh token lifetime (days)       | `7`                         | No       |
| `REDIS_ENABLED`                  | Enable Redis recommendation cache   | `true`                      | No       |
| `REDIS_URL`                      | Redis connection URL                | `redis://localhost:6379/0`  | No       |
| `RECOMMENDATION_CACHE_TTL_SECONDS` | Recommendation cache TTL          | `300`                       | No       |
| `CORS_ORIGINS`                   | Allowed CORS origins                | `["http://localhost:3000"]` | No       |
| `FRONTEND_URL`                   | SPA base URL (auth redirects)       | `http://localhost:3000`     | No       |
| `DEBUG`                          | Enable debug mode                   | `False`                     | No       |
| `LOG_LEVEL`                      | Logging level                       | `INFO`                      | No       |
| `POSTGRES_DB`                    | PostgreSQL database name            | `icap_db`                   | Docker   |
| `POSTGRES_USER`                  | PostgreSQL user                     | `icap_user`                 | Docker   |
| `POSTGRES_PASSWORD`              | PostgreSQL password                 | —                           | Docker   |

---

## 🐳 Docker

### Development

```bash
# Build and start all services
docker-compose up --build -d

# View real-time logs
docker-compose logs -f backend

# Access the database
docker-compose exec db psql -U icap_user -d icap_db

# Run migrations inside container
docker-compose exec backend alembic upgrade head

# Shut everything down
docker-compose down

# Shut down and remove volumes (clean slate)
docker-compose down -v
```

### Production

```bash
# Build production image
docker build -t icap-backend:latest ./backend

# Run with production settings
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host:5432/icap_db \
  -e SECRET_KEY=your-production-secret \
  icap-backend:latest
```

---

## 🧪 Testing

```bash
# Run all backend tests
cd backend
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=app --cov-report=html

# Run Milestone 3 regression slice
pytest tests/test_habit_score.py \
  tests/test_behavioral_analytics.py \
  tests/test_recommendations.py \
  tests/test_e2e_wake_workflow.py -q

# Run specific test file
pytest tests/test_auth.py

# Run tests matching a pattern
pytest -k "test_login"
```

```bash
# Frontend smoke tests
cd frontend
npm test -- --watchAll=false
```

Open `htmlcov/index.html` to view the coverage report in your browser.

---

## 🗺️ Milestone Roadmap

| Milestone   | Focus Area                              | Status         |
| ----------- | --------------------------------------- | -------------- |
| **M1** 🔐   | Auth, Users, Profiles, DevOps           | 🟢 Completed   |
| **M2** ⏰   | Alarm CRUD, Scheduling, Attempt Logs    | 🟢 Completed   |
| **M3** 🧩   | Challenges, Habit Score, Recommendations| 🟢 Completed   |
| **M4** 📊   | Deeper Sleep Insights & Trends          | 🔵 Planned     |
| **M5** 🌐   | Frontend Enhancements & PWA             | 🔵 Planned     |
| **M6** 📱   | Mobile App (React Native)               | 🔵 Planned     |
| **M7** 🎯   | Advanced Personalization                | 🔵 Planned     |
| **M8** 🚀   | Production Deploy & Scaling             | 🔵 Planned     |

> Milestone 3 demo notes and attempt-log audit steps: [docs/MILESTONE_3_CLOSEOUT.md](docs/MILESTONE_3_CLOSEOUT.md).

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
- Maintain **test coverage** above 80%

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
