# Use official Python 3.12 slim base image
FROM python:3.12-slim

# Set working directory for the application
WORKDIR /srv/iocfetcher

# Install Poetry
RUN pip install --no-cache-dir poetry

# Copy project files
COPY pyproject.toml poetry.lock ./
COPY iocfetcher ./iocfetcher

# Install dependencies
RUN poetry config virtualenvs.create false && poetry install --no-root --no-interaction --no-ansi

# Expose port
EXPOSE 8000

# Set /app for mounting configuration files
VOLUME ["/app"]

# Command to run the FastAPI application with a configurable config file
CMD ["python", "-m", "iocfetcher.app", "-c", "/app/config.yaml"]
