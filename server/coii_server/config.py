from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./coii.db"
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False

    model_config = {"env_prefix": "COII_", "env_file": ".env"}


settings = Settings()
