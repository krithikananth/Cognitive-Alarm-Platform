FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install system libraries needed by the PostgreSQL client (psycopg2)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libpq5 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies from requirements.txt (includes psycopg2-binary)
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && python -c "import psycopg2"

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Start the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
