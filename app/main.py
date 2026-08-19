import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db_init import init_db
from app.routes import admin, auth, additional_data, chat_folders, chats, documents, users
from app.services.email import email_configured, get_email_provider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

init_db()

app = FastAPI(title="Chatbot API", version="1.0.0")

provider = get_email_provider()
if provider == "gmail":
    logger.info("Email configured via Gmail API (%s)", settings.gmail_from or settings.gmail_sender or settings.smtp_user)
elif provider == "resend":
    logger.info("Email configured via Resend")
elif provider == "smtp":
    logger.info("Email configured via SMTP (%s)", settings.smtp_user)
else:
    logger.warning(
        "Email is NOT configured. Set EMAIL_PROVIDER=gmail with Gmail OAuth vars, or RESEND_API_KEY, or SMTP settings."
    )
origins = [origin.strip() for origin in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(chats.router)
app.include_router(chat_folders.router)
app.include_router(additional_data.router)
app.include_router(documents.router)
app.include_router(admin.router)


@app.get("/health")
def health():
    return {"status": "ok", "email_configured": email_configured(), "email_provider": get_email_provider()}
