# Use official Python 3.14 slim base image
FROM python:3.14-slim

# Set working directory for the application
WORKDIR /srv/iocfetcher

# Install required system packages for building pytricia
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libffi-dev \
    build-essential

# Install Poetry
RUN pip install --no-cache-dir poetry

# Copy project files
COPY pyproject.toml poetry.lock ./
COPY iocfetcher ./iocfetcher

# Install dependencies
RUN poetry config virtualenvs.create false && poetry install --no-root --no-interaction --no-ansi

# Remove build dependencies
RUN apt-get purge -y gcc python3-dev libffi-dev build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Expose port
EXPOSE 8000

# Set /app for mounting configuration files
VOLUME ["/app"]

# Command to run the FastAPI application with a configurable config file
CMD ["python", "-m", "iocfetcher.app", "-c", "/app/config.yaml"]
