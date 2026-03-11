from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:root@localhost:5432/techtrek"
    secret_key: str = "techtrek-dev-secret-change-in-production"
    debug: bool = True
    hold_timeout_minutes: int = 5
    priority_window_hours: int = 24

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""

    company_name: str = "TechTrek Pvt Ltd"
    company_address: str = "123 Tech Park, Bangalore, Karnataka 560001"
    company_gstin: str = "29AABCT1234F1ZH"
    company_pan: str = "AABCT1234F"
    company_email: str = "billing@techtrek.in"
    company_phone: str = "+91 80 1234 5678"
    gst_rate: float = 18.0

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@techtrek.in"
    smtp_from_name: str = "TechTrek"

    babel_default_locale: str = "en"
    babel_default_timezone: str = "Asia/Kolkata"

    model_config = {"env_file": ".env"}


settings = Settings()
