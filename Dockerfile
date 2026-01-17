# Use Python 3.12 slim as base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install build dependencies and cleanup in one layer to keep image size down
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only pyproject.toml and other build files first
COPY pyproject.toml ./
COPY README.md ./
COPY sse_starlette ./sse_starlette

# Install package with all dependencies
RUN pip install --no-cache-dir -e .

# Install additional test dependencies if needed
# You can also add these to pyproject.toml in [project.optional-dependencies]
RUN pip install --no-cache-dir pytest pytest-asyncio httpx uvicorn

# Copy test files
COPY tests ./tests

# Expose port
EXPOSE 8000

# Set Python path
ENV PYTHONPATH=/app

# Default command - this can be overridden by testcontainers
CMD ["uvicorn", "tests.integration.main_endless_conditional:app", "--host", "0.0.0.0", "--port", "8000"]
