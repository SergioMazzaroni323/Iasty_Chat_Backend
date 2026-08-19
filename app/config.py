from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./chatbot.db"
    secret_key: str = "dev-secret-key-change-in-production"
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    gpt_provider: str = "openai"  # openai | openrouter
    serpapi_api_key: str = ""
    cors_origins: str = "http://localhost:3000"
    admin_email: str = ""
    storage_timezone: str = "UTC"
    max_pdf_upload_bytes: int = 10 * 1024 * 1024
    max_pdf_pages: int = 100
    max_pdf_text_chars: int = 100_000
    rag_enabled: bool = True
    rag_top_k: int = 6
    rag_recent_messages: int = 4
    rag_min_messages: int = 1
    rag_chunk_size: int = 500
    rag_min_similarity: float = 0.15
    embedding_model: str = "text-embedding-3-small"
    qdrant_url: str = ""
    qdrant_path: str = "./qdrant_data"
    qdrant_api_key: str = ""
    qdrant_collection: str = "chat_messages"
    qdrant_timeout_seconds: float = 5.0
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    frontend_url: str = "http://localhost:3000"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "Iasty"
    smtp_use_ssl: bool = False
    resend_api_key: str = ""
    resend_from: str = "Iasty <onboarding@resend.dev>"
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    gmail_from: str = ""
    gmail_sender: str = ""
    email_provider: str = "auto"  # auto | smtp | resend | gmail
    email_verify_expire_hours: int = 24
    password_reset_expire_hours: int = 1

    @field_validator("smtp_password", mode="before")
    @classmethod
    def normalize_smtp_password(cls, value: object) -> object:
        if isinstance(value, str):
            return value.replace(" ", "")
        return value

    class Config:
        env_file = ".env"


settings = Settings()
