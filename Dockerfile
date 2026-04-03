FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install required system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libpq-dev \
    librdkafka-dev \
    libssl-dev \
    libffi-dev \
    pkg-config \
    cargo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip to latest
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# Copy project files
COPY pyproject.toml README.md ./

# Install standard dependencies (excluding local folders initially)
RUN pip install --no-cache-dir .

# Copy source maps
COPY . .

# Install the application logic
RUN pip install --no-cache-dir .

# Default command (overridden by docker-compose)
CMD ["python", "services/api_gateway/main.py"]
