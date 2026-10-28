from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict


class TrafficProfile(str, Enum):
    DEFAULT = "default"
    DEMO = "demo"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRAFFIC_", env_file=".env", extra="ignore")

    PROFILE: TrafficProfile = TrafficProfile.DEFAULT
    DATABASE_URL: str = "sqlite+aiosqlite:///traffic.db"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "*"]


settings = Settings()
