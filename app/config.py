from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment / .env file.

    Stripe credentials must always come from environment variables
    (STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET). They are never hardcoded.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./metering.db"

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_pro_price_id: str = "price_pro_test_placeholder"
    stripe_success_url: str = "http://localhost:8000/billing/success"
    stripe_cancel_url: str = "http://localhost:8000/billing/cancel"

    rollup_interval_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
