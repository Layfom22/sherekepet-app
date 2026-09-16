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

    # Timezone
    DEFAULT_TIMEZONE: str = "America/Lima"

    # RENIEC API
    APIS_NET_PE_TOKEN: str = "apis-token-13012.n93cG7Vp3E9tcRGXgvH8Hw0UWH31aBRQ"

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
