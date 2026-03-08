from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:root@localhost:5432/techtrek"
    secret_key: str = "techtrek-dev-secret-change-in-production"
    debug: bool = True
    hold_timeout_minutes: int = 5
    priority_window_hours: int = 24

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@techtrek.in"
    smtp_from_name: str = "TechTrek"

    model_config = {"env_file": ".env"}


settings = Settings()
