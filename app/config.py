from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from the repo root so OPENAI_API_KEY etc. load correctly even if cwd is not the project folder.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Force .env values to override any stale system environment variables.
load_dotenv(_PROJECT_ROOT / ".env", override=True)


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:root@localhost:5432/techtrek"
    secret_key: str = ""
    debug: bool = False

    # Field-level encryption key (Fernet, 44-char URL-safe base64).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    field_encryption_key: str = ""

    @model_validator(mode="after")
    def _require_strong_secrets(self) -> "Settings":
        if len(self.secret_key) < 32:
            raise ValueError(
                "SECRET_KEY must be set in the environment and be at least 32 characters long. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if not self.field_encryption_key:
            raise ValueError(
                "FIELD_ENCRYPTION_KEY must be set in the environment. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        # Validate that the value is actually a well-formed Fernet key so we
        # get a clear startup error instead of a cryptic traceback on the first
        # DB read/write.
        try:
            from cryptography.fernet import Fernet
            Fernet(self.field_encryption_key.encode())
        except Exception as exc:
            raise ValueError(
                "FIELD_ENCRYPTION_KEY is not a valid Fernet key (must be a 44-char "
                "URL-safe base64 string). "
                "Generate a correct one with: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            ) from exc
        return self
    hold_timeout_minutes: int = 5
    priority_window_hours: int = 24

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""

    # Email of the first admin user. When set, only this email gets admin on registration.
    # Falls back to first-registrant-wins if not configured (dev convenience only).
    admin_bootstrap_email: str = ""

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

    base_url: str = "https://192.168.10.82:8000"

    # Optional: admin certificate AI (two OpenAI calls per generation — image + vision layout).
    # Stripped below; surrounding quotes removed so OPENAI_API_KEY="sk-..." in .env works.
    openai_api_key: str = ""

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _normalize_openai_api_key(cls, v: object) -> str:
        if v is None:
            return ""
        s = str(v).strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
            s = s[1:-1].strip()
        return s
    openai_cert_image_model: str = "gpt-image-1.5"
    openai_cert_image_quality: str = "medium"
    openai_cert_layout_model: str = "gpt-5.4-mini"
    openai_metrics_report_model: str = "gpt-5.4-mini"

    google_client_id: str = ""
    google_client_secret: str = ""

    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
