from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./techtrak.db"
    secret_key: str = "techtrek-dev-secret-change-in-production"
    debug: bool = True
    hold_timeout_minutes: int = 5
    priority_window_hours: int = 24

    model_config = {"env_file": ".env"}


settings = Settings()
