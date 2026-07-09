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
  <a href="https://www.postgresql.org/"><img src="https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL"/></a>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker"/></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License"/></a>
  <img src="https://img.shields.io/badge/Status-In_Development-orange?style=flat-square" alt="Status"/>
</p>

---

## 📖 About

The **Intelligent Cognitive Alarm Platform (ICAP)** is a next-generation alarm system that goes beyond simple wake-up calls. It combines cognitive challenges, personalized difficulty scaling, and sleep analytics to help users build healthier morning routines and sharpen their minds from the moment they wake up.

Unlike traditional alarm apps, ICAP requires users to solve cognitive challenges — math problems, memory puzzles, pattern recognition tasks — before the alarm can be dismissed. The platform learns from user behavior and adapts challenge difficulty over time.

---

## 🏗️ Architecture Overview

ICAP follows a **modular monolith** architecture built with FastAPI, designed to evolve into microservices as the platform scales. The backend exposes a RESTful API consumed by web and mobile clients.

```
┌─────────────────────────────────────────────────────┐
│                   Client Layer                       │
│         (Next.js Web App / Mobile App)               │
└──────────────────────┬──────────────────────────────┘
                       │ HTTPS / REST
┌──────────────────────▼──────────────────────────────┐
│                  API Gateway                         │
│              (FastAPI + Uvicorn)                      │
├──────────┬───────────┬───────────┬──────────────────┤
│  Auth    │  Alarm    │ Challenge │   Analytics      │
│ Service  │  Service  │  Engine   │    Engine         │
├──────────┴───────────┴───────────┴──────────────────┤
│              Data Access Layer                       │
│           (SQLAlchemy ORM + Alembic)                 │
├─────────────────────────────────────────────────────┤
│            PostgreSQL / SQLite                        │
└─────────────────────────────────────────────────────┘
```

> For detailed architecture documentation, see [docs/architecture.md](docs/architecture.md).

---

## ✨ Features — Milestone 1

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
| **Frontend**   | Next.js (planned)           | Web client (Milestone 3)         |
| **DevOps**     | Docker / Docker Compose     | Containerization & orchestration |
| **Testing**    | pytest / httpx              | Unit & integration testing       |
| **Docs**       | Swagger UI / ReDoc          | Interactive API documentation    |

---

## 🚀 Getting Started

### Prerequisites

- **Python** 3.11 or higher
- **PostgreSQL** 16 (or use Docker)
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

#### 3. Install dependencies

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

### Running with Docker (Recommended)

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

---

## 📡 API Endpoints

### Authentication

| Method | Endpoint              | Description              | Auth Required |
| ------ | --------------------- | ------------------------ | ------------- |
| POST   | `/api/v1/auth/register` | Register a new user      | ❌             |
| POST   | `/api/v1/auth/login`    | Login & get JWT tokens   | ❌             |
| POST   | `/api/v1/auth/refresh`  | Refresh access token     | 🔑             |
| POST   | `/api/v1/auth/logout`   | Invalidate tokens        | 🔑             |

### Users

| Method | Endpoint              | Description              | Auth Required |
| ------ | --------------------- | ------------------------ | ------------- |
| GET    | `/api/v1/users/me`      | Get current user profile | 🔑             |
| PUT    | `/api/v1/users/me`      | Update current user      | 🔑             |
| GET    | `/api/v1/users`         | List all users (admin)   | 🔑 Admin      |
| GET    | `/api/v1/users/{id}`    | Get user by ID (admin)   | 🔑 Admin      |
| DELETE | `/api/v1/users/{id}`    | Delete user (admin)      | 🔑 Admin      |

### Profile

| Method | Endpoint                 | Description            | Auth Required |
| ------ | ------------------------ | ---------------------- | ------------- |
| GET    | `/api/v1/profile`          | Get user profile       | 🔑             |
| PUT    | `/api/v1/profile`          | Update user profile    | 🔑             |
| PATCH  | `/api/v1/profile/preferences` | Update preferences  | 🔑             |

### Health

| Method | Endpoint       | Description             | Auth Required |
| ------ | -------------- | ----------------------- | ------------- |
| GET    | `/health`        | Health check            | ❌             |
| GET    | `/`              | Root / welcome message  | ❌             |

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
│   │   │       │   └── profile.py
│   │   │       └── router.py       # API router aggregation
│   │   ├── core/
│   │   │   ├── config.py           # App configuration
│   │   │   ├── security.py         # JWT & password utils
│   │   │   └── database.py         # Database connection
│   │   ├── models/                 # SQLAlchemy models
│   │   │   ├── user.py
│   │   │   └── profile.py
│   │   ├── schemas/                # Pydantic schemas
│   │   │   ├── user.py
│   │   │   └── profile.py
│   │   ├── services/               # Business logic
│   │   │   ├── auth_service.py
│   │   │   └── user_service.py
│   │   └── main.py                 # FastAPI app entry point
│   ├── tests/                      # Test suite
│   │   ├── conftest.py
│   │   ├── test_auth.py
│   │   └── test_users.py
│   ├── alembic.ini                 # Alembic configuration
│   ├── Dockerfile                  # Backend container
│   └── requirements.txt            # Python dependencies
├── frontend/                       # Next.js app (Milestone 3)
├── docs/
│   ├── architecture.md             # Architecture documentation
│   ├── database_design.md          # Database schema design
│   └── api_documentation.md        # API reference
├── docker-compose.yml              # Multi-container orchestration
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🔐 Environment Variables

| Variable              | Description                    | Default                     | Required |
| --------------------- | ------------------------------ | --------------------------- | -------- |
| `DATABASE_URL`        | PostgreSQL connection string   | `sqlite:///./icap.db`       | Yes      |
| `SECRET_KEY`          | JWT signing secret             | —                           | Yes      |
| `ALGORITHM`           | JWT algorithm                  | `HS256`                     | No       |
| `ACCESS_TOKEN_EXPIRE` | Access token lifetime (mins)   | `30`                        | No       |
| `REFRESH_TOKEN_EXPIRE`| Refresh token lifetime (days)  | `7`                         | No       |
| `CORS_ORIGINS`        | Allowed CORS origins           | `["http://localhost:3000"]` | No       |
| `DEBUG`               | Enable debug mode              | `False`                     | No       |
| `LOG_LEVEL`           | Logging level                  | `INFO`                      | No       |
| `POSTGRES_DB`         | PostgreSQL database name       | `icap_db`                   | Docker   |
| `POSTGRES_USER`       | PostgreSQL user                | `icap_user`                 | Docker   |
| `POSTGRES_PASSWORD`   | PostgreSQL password            | —                           | Docker   |

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
# Run all tests
cd backend
pytest

# Run with verbose output
pytest -v

# Run with coverage report
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_auth.py

# Run tests matching a pattern
pytest -k "test_login"
```

Open `htmlcov/index.html` to view the coverage report in your browser.

---

## 🗺️ Milestone Roadmap

| Milestone   | Focus Area                     | Status         |
| ----------- | ------------------------------ | -------------- |
| **M1** 🔐   | Auth, Users, Profiles, DevOps  | 🟢 In Progress |
| **M2** ⏰   | Alarm CRUD, Scheduling Engine  | 🔵 Planned     |
| **M3** 🧩   | Challenge Engine & Difficulty   | 🔵 Planned     |
| **M4** 📊   | Analytics & Sleep Insights     | 🔵 Planned     |
| **M5** 🌐   | Next.js Frontend               | 🔵 Planned     |
| **M6** 📱   | Mobile App (React Native)      | 🔵 Planned     |
| **M7** 🤖   | AI-Powered Personalization     | 🔵 Planned     |
| **M8** 🚀   | Production Deploy & Scaling    | 🔵 Planned     |

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
