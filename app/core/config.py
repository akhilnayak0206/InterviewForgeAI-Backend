from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    DB_ECHO: bool = False

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "InterviewForgeAI"

    # --- JWT Configuration ---------------------------------------------------
    # SECRET_KEY is used to sign JWT tokens. In production, this MUST be
    # a long, random, unguessable string loaded from the environment.
    # Generate one with: openssl rand -hex 32
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"

    # Token lifetime in minutes. 360 min is a reasonable default —
    # short enough to limit damage if stolen, long enough to not annoy users.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 360

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()