# — Stage 1: Builder ————————
# This stage installs build tools and compiles Python dependencies.
# None of the build tools end up in the final image.
FROM python:3.12-slim AS builder

WORKDIR /app

# Install system dependencies needed to COMPILE Python packages.
# - build-essential: gcc, make (needed by C extensions)
# - libpq-dev: PostgreSQL client library headers (needed by psycopg)
# We clean up apt cache in the same RUN to keep the layer small.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency files first. This layer is cached and only
# rebuilds when pyproject.toml or uv.lock change — not when
# application code changes.
COPY pyproject.toml uv.lock ./

# Install uv (fast Python package installer) and use it to install
# all project dependencies into the system Python.
# --no-cache: don't store download cache in the image.
# --system: install into system site-packages, not a virtualenv.
RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache .

# — Stage 2: Runtime ————————
# This stage contains only what's needed to RUN the application.
# No compilers, no header files, no build tools.
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install only the RUNTIME system libraries (not -dev headers).
# - libpq5: PostgreSQL client library (needed by psycopg at runtime)
# - curl: used by Docker health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user. Running as root inside containers is a
# security risk — if an attacker escapes the container, they're root.
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

# Copy compiled Python packages from the builder stage.
# This is the key multi-stage trick: we get the compiled .so files
# without carrying over gcc, make, and header files.
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code and Alembic configuration.
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY app/ ./app/

# Copy entrypoint scripts.
COPY scripts/ ./scripts/
RUN chmod +x ./scripts/*.sh

# Create uploads directory owned by appuser.
RUN mkdir -p /app/uploads && chown -R appuser:appuser /app/uploads

# Switch to non-root user for all subsequent commands.
USER appuser

# Document the port this container listens on.
# EXPOSE does not publish the port — that's done in docker-compose.yml.
EXPOSE 8000

# Default command: run Uvicorn in production mode.
# - 0.0.0.0: accept connections from the Docker network (not just localhost)
# - No --reload: the image is immutable, there's nothing to reload.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]