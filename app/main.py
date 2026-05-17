import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.database import engine

# Load environment variables
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
HOST = os.getenv("HOST", "0.0.0.0" if not DEBUG else "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs during application startup and shutdown.
    """

    try:
        with engine.connect() as connection:
            print("Database connection successful")

    except Exception as error:
        print("Failed to connect to database")
        print(error)
        raise

    yield

    print("Application shutting down")


# Create FastAPI app
app = FastAPI(
    title="InterviewForgeAI Backend",
    description="Backend API for InterviewForgeAI",
    version="0.1.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Hello from InterviewForgeAI backend"}


@app.get("/health")
def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy", "service": "InterviewForgeAI Backend"}


def main():
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,
        log_level="debug" if DEBUG else "info"
    )


if __name__ == "__main__":
    main()
