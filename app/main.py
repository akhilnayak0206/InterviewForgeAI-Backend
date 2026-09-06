import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.graph import close_checkpointer, init_checkpointer
from app.documents.router import router as document_router
from app.jobs.queue import close_arq_pool
from app.redis.client import close_redis_pool, init_redis_pool
from app.routes import (
    auth_router,
    chat_router,
    interview_workflow_router,
    job_router,
    message_router,
    session_router,
    user_router,
)

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000",
).split(",")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with engine.connect() as connection:
            print("Database connection successful", connection.engine.url)

    except Exception as error:
        print("Failed to connect to database")
        print(error)
        raise

    # Initialize shared LangGraph PostgreSQL checkpointer
    try:
        await init_checkpointer()
    except Exception as error:
        print("Failed to initialize checkpointer:")
        print(error)
        print("Workflows will not be available.")

    # Initialize Redis pool for cache, rate limiting, and locks.
    # If Redis is unavailable, features degrade gracefully.
    await init_redis_pool()

    yield

    # Cleanup: close the checkpointer pool
    await close_checkpointer()
    await close_arq_pool()
    await close_redis_pool()
    print("Application shutting down")


# Create FastAPI app
app = FastAPI(
    title="InterviewForgeAI Backend",
    description="Backend API for InterviewForgeAI",
    version="0.1.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(
    request: Request,
    exc: Exception,
):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
        },
    )


app.include_router(
    auth_router,
    prefix=settings.API_V1_STR,
)

app.include_router(
    user_router,
    prefix=settings.API_V1_STR,
)

app.include_router(
    session_router,
    prefix=settings.API_V1_STR,
)

app.include_router(
    message_router,
    prefix=settings.API_V1_STR,
)

app.include_router(
    chat_router,
    prefix=settings.API_V1_STR,
)

app.include_router(
    interview_workflow_router,
    prefix=settings.API_V1_STR,
)

app.include_router(
    document_router,
    prefix=settings.API_V1_STR,
)

app.include_router(
    job_router,
    prefix=settings.API_V1_STR,
)


@app.get("/")
def root():
    return {"message": "Hello from InterviewForgeAI backend"}


@app.get("/health")
def health_check():
    checks = {
        "service": "InterviewForgeAI Backend",
        "environment": settings.ENVIRONMENT,
    }

    # Check database connectivity
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception:
        checks["database"] = "unavailable"

    # Check Redis connectivity
    from app.redis.client import get_redis_client

    redis_client = get_redis_client()
    checks["redis"] = "connected" if redis_client is not None else "unavailable"

    # Overall status: healthy if database is connected
    # (Redis is optional — the app degrades gracefully without it)
    checks["status"] = "healthy" if checks["database"] == "connected" else "degraded"

    status_code = 200 if checks["status"] == "healthy" else 503
    return JSONResponse(content=checks, status_code=status_code)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,
        log_level="debug" if DEBUG else "info",
    )
