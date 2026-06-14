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

    # ── OpenAI Configuration ─────────────────────────────────────

    # API key for authenticating with OpenAI (or compatible provider).
    # Never commit this. Always load from environment.
    OPENAI_API_KEY: str

    # Which model to use. gpt-4o-mini is fast, cheap, and good enough for
    # most interview coaching tasks. Upgrade to gpt-4o for harder topics.
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Maximum tokens the model can generate in its response.
    # This does NOT include prompt tokens — it's output-only.
    # 1024 is ~750 words, plenty for an interview question + explanation.
    OPENAI_MAX_TOKENS: int = 1024

    # Temperature controls randomness: 0.0 = deterministic, 1.0 = creative.
    # 0.7 is a sweet spot for interview coaching — structured but not robotic.
    OPENAI_TEMPERATURE: float = 0.7

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
