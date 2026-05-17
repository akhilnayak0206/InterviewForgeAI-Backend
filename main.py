import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
HOST = os.getenv("HOST", "0.0.0.0" if not DEBUG else "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# Create FastAPI app
app = FastAPI(
    title="InterviewForgeAI Backend",
    description="Backend API for InterviewForgeAI",
    version="0.1.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api1")
def read_root1():
    return {"message": "try"}


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
        "main:app",
        host=HOST,
        port=PORT,
        reload=DEBUG,
        log_level="debug" if DEBUG else "info"
    )


if __name__ == "__main__":
    main()
