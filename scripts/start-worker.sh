#!/bin/bash
# — Worker Entrypoint ————————
#
# Starts the ARQ worker process. The worker:
#   1. Connects to Redis (job queue)
#   2. Polls for enqueued jobs
#   3. Executes jobs (which connect to PostgreSQL, call LLM APIs, etc.)
#
# The worker does NOT:
#   - Run migrations (that's the API container's job)
#   - Serve HTTP requests
#   - Need an exposed port

set -e

echo "═══ ForgeAI Worker Entrypoint ═══"
echo "Environment: ${ENVIRONMENT:-development}"
echo "Starting ARQ worker..."

# exec replaces the shell with the ARQ process.
# This ensures SIGTERM goes directly to the worker for graceful shutdown.
exec arq app.jobs.worker.WorkerSettings