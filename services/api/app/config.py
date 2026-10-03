from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "dubbing-platform"
    provider_mode: str = "mock"
    whisper_model: str = "small"
    # "cuda" on the Windows GPU worker. Empty compute type picks int8 on CPU
    # and float16 on CUDA.
    whisper_device: str = "cpu"
    whisper_compute_type: str = ""
    # Spoken rewrite. A small model copies the literal draft, so formulas need
    # a full instruct model. An empty URL keeps the Argos line.
    ollama_base_url: str = "http://127.0.0.1:11434"
    rewrite_model: str = "qwen3.8:27b"
    cors_origins: str = "http://localhost:3000"
    api_dev_token: str = "dev-token"

    database_url: str = "postgresql+psycopg://dubbing:dubbing@localhost:5432/dubbing"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "dubbing"
    s3_region: str = "us-east-1"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
