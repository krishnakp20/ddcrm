from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/ddcrm"
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    CORS_ORIGINS: str = "http://localhost:5173"
    TIMEZONE: str = "Asia/Kolkata"

    ADMIN_NAME: str = "Admin"
    ADMIN_EMAIL: str = "admin@dialdesk.in"
    ADMIN_PASSWORD: str = "admin123"

    # Public address of the frontend; used to build links in emails and messages
    APP_BASE_URL: str = "http://localhost:5173"
    TRUST_FORWARDED_FOR: bool = False   # true only behind your own reverse proxy: the dialer IP is then read from X-Forwarded-For
    UPLOAD_DIR: str = "uploads"

    # Email (SMTP). Leave SMTP_HOST empty and messages are only recorded in the notification log.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "DialDesk <no-reply@dialdesk.in>"
    SMTP_STARTTLS: bool = True

    # SMS and WhatsApp: any HTTP provider. The CRM POSTs {"to": ..., "message": ...} with the key as a
    # Bearer token. Leave the URL empty and messages are only recorded in the notification log.
    SMS_API_URL: str = ""
    SMS_API_KEY: str = ""
    WHATSAPP_API_URL: str = ""
    WHATSAPP_API_KEY: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
