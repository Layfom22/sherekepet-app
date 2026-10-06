from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "SherekePet"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "sqlite:///./sherekeepet.db"

    # JWT Security
    SECRET_KEY: str = "supersecret_jwt_key_sherekeepet_change_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # CORS Origins permitidos (separados por coma)
    ALLOWED_ORIGINS: str = "https://sherekepet.com,https://www.sherekepet.com,http://localhost:8000,http://127.0.0.1:8000"

    # Timezone
    DEFAULT_TIMEZONE: str = "America/Lima"

    # RENIEC API (Configurar en .env en producción)
    APIS_NET_PE_TOKEN: str = ""

    # Cloudflare R2 Storage (S3-compatible)
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY: str = ""
    R2_SECRET_KEY: str = ""
    R2_BUCKET_NAME: str = "sherekepet"
    R2_PUBLIC_URL: str = ""

    # Google OAuth (Leído de variables de entorno o .env)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""

    # Configuración SMTP (Hotmail / Outlook / Gmail / Personalizado)
    SMTP_HOST: str = "smtp.office365.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""
    SMTP_TLS: bool = True

    # Resend API Key para correos transaccionales y marca blanca
    RESEND_API_KEY: str = ""

    # Pasarela de Pagos SaaS (Mercado Pago & Yape/Plin Directo)
    MP_ENABLED: bool = False
    MP_ACCESS_TOKEN: str = ""
    MP_PUBLIC_KEY: str = ""
    MP_WEBHOOK_SECRET: str = ""
    YAPE_PLIN_TITULAR: str = "PROJECT DC HOLDING E.I.R.L."
    YAPE_PLIN_NUMERO: str = "999 888 777"
    YAPE_PLIN_QR_URL: str = ""
    SOPORTE_EMAIL: str = "roggerjjj@gmail.com"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()

