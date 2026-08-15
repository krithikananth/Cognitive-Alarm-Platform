#!/bin/sh
# Container start sequence for platforms that override the Dockerfile CMD
# (Render passes the command through a shell, which mangles inline quoting).
set -e

python -c 'from app.main import Base, engine; Base.metadata.create_all(bind=engine)'
alembic upgrade head

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    --no-access-log
