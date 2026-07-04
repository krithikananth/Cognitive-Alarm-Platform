# Intelligent Cognitive Alarm Platform

AI-powered platform that helps users develop consistent wake-up habits through personalized cognitive challenges.

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose

### 1. Start Databases (Docker)
```bash
docker-compose up -d postgres mongodb redis
```

### 2. Backend Setup
```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Seed challenge bank (200+ challenges)
python -m app.scripts.seed_challenges

# Start the API server
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup
```bash
cd frontend
npm install
npm start
```

### 4. Access
- **Frontend**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Tech Stack
- **Backend**: Python, FastAPI, SQLAlchemy, Alembic
- **Frontend**: React 18, Tailwind CSS, Zustand
- **Databases**: PostgreSQL, MongoDB, Redis
- **Auth**: JWT + OAuth2 (Google, GitHub)
- **AI/ML**: Scikit-learn, XGBoost (adaptive difficulty)

## Project Structure
```
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI entry point
│   │   ├── config.py         # Settings
│   │   ├── database.py       # DB connections
│   │   ├── models/           # SQLAlchemy models
│   │   ├── schemas/          # Pydantic schemas
│   │   ├── routers/          # API endpoints
│   │   ├── services/         # Business logic
│   │   ├── middleware/       # Auth, rate limiting
│   │   ├── ai/               # ML models
│   │   ├── scripts/          # Seed scripts
│   │   └── utils/            # Helpers
│   ├── alembic/              # DB migrations
│   └── tests/                # Pytest tests
├── frontend/
│   ├── src/
│   │   ├── pages/            # React pages
│   │   ├── components/       # Reusable components
│   │   ├── store/            # Zustand stores
│   │   └── services/         # API client
│   └── public/
├── docker-compose.yml
└── .env
```
