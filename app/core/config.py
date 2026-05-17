from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    DB_ECHO: bool = False

    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "InterviewForgeAI"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
