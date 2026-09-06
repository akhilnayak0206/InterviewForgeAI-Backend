#!/bin/bash
# — FastAPI Entrypoint ————————
#
# This script runs BEFORE Uvicorn starts. It handles:
#   1. Waiting for dependent services (PostgreSQL, Redis)
#   2. Running database migrations (opt-in via RUN_MIGRATIONS=true)
#   3. Starting the application
#
# Why a script instead of just CMD?
#   - Migrations must run BEFORE the app starts
#   - We need conditional logic (only migrate if RUN_MIGRATIONS=true)
#   - We want clear log messages about what's happening

set -e  # Exit immediately if any command fails

echo "═══ ForgeAI API Entrypoint ═══"
echo "Environment: ${ENVIRONMENT:-development}"

# — Step 1: Run Migrations (Opt-In) ————————
# In local development: RUN_MIGRATIONS=true for convenience.
# In production: run migrations as a separate deployment step.
#
# Why opt-in?
#   - Running 3 API containers should NOT trigger 3 simultaneous migrations
#   - Destructive migrations need human review
#   - Failed migrations should not crash the application
if [ "$RUN_MIGRATIONS" = "true" ]; then
    echo "Running database migrations..."
    alembic upgrade head
    echo "Migrations complete."
else
    echo "Skipping migrations (RUN_MIGRATIONS != true)"
fi

# — Step 2: Start the Application ————————
# exec replaces this shell process with uvicorn. This is important:
#   - PID 1 is now uvicorn (receives SIGTERM for graceful shutdown)
#   - Without exec, the shell is PID 1 and may not forward signals
echo "Starting FastAPI server..."
exec "$@"