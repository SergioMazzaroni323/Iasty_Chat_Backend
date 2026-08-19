# Iasty — Backend

FastAPI API server for [Iasty](../README.md): multi-model AI chat, RAG, auth, and streaming responses.

---

## Tech Stack

| Technology | Purpose |
|------------|---------|
| **FastAPI** | REST API + SSE streaming |
| **Uvicorn** | ASGI server |
| **SQLAlchemy 2** | ORM (SQLite by default) |
| **python-jose** | JWT authentication |
| **passlib + bcrypt** | Password hashing |
| **httpx** | OpenAI, OpenRouter, SerpAPI |
| **Qdrant** | Vector store for RAG |
| **pypdf / python-docx** | Document parsing |

---

## Quick Start

### Prerequisites

- Python **3.11+**
- At least one LLM key: `OPENAI_API_KEY` and/or `OPENROUTER_API_KEY`

### Setup

```powershell
cd Backend
python -m pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` with your API keys and secrets.

### Run

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

| URL | Description |
|-----|-------------|
| http://localhost:8000/health | Health check + email status |
| http://localhost:8000/docs | Interactive OpenAPI docs |

---

## Project Structure

```
Backend/
├── app/
│   ├── main.py              # App entry, CORS, routers
│   ├── config.py            # Settings from .env
│   ├── db_init.py           # Schema + migrations on startup
│   ├── models.py            # SQLAlchemy models
│   ├── schemas.py           # Pydantic request/response models
│   ├── auth.py              # JWT, tiers, token limits
│   ├── constants.py         # Models, prompts, availability checks
│   ├── routes/
│   │   ├── auth.py          # Register, login, verify, reset password
│   │   ├── users.py         # Profile, plan updates
│   │   ├── chats.py         # Chats, messages (SSE), /config
│   │   ├── chat_folders.py  # Folder CRUD
│   │   ├── additional_data.py
│   │   ├── documents.py     # PDF parsing
│   │   └── admin.py         # Admin stats & user management
│   └── services/
│       ├── llm.py           # Provider routing + fallback
│       ├── openai.py / openrouter.py / serpapi.py
│       ├── rag.py / qdrant_store.py / embeddings.py
│       ├── email.py / gmail_api.py / auth_tokens.py
│       └── pdf.py / file_parser.py / tokens.py
├── scripts/
│   ├── gmail_authorize.py   # One-time Gmail OAuth setup
│   └── test_email.py
├── requirements.txt
└── .env.example
```

---

## Environment Variables

Copy `.env.example` to `.env`.

### Core

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Default: `sqlite:///./chatbot.db` |
| `SECRET_KEY` | JWT signing secret (use a long random string in production) |
| `CORS_ORIGINS` | e.g. `http://localhost:3000` |
| `FRONTEND_URL` | Base URL for verification / reset links |
| `ADMIN_EMAIL` | Auto-promoted to admin on register/login |

### AI & Search

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | GPT models + embeddings |
| `OPENROUTER_API_KEY` | Claude, Gemini, Grok; GPT fallback |
| `GPT_PROVIDER` | `openai` (default) or `openrouter` |
| `SERPAPI_API_KEY` | Web search (Plus tier) |
| `EMBEDDING_MODEL` | Default: `text-embedding-3-small` |

### RAG (Qdrant)

| Variable | Description |
|----------|-------------|
| `QDRANT_URL` | Leave empty for local `./qdrant_data` |
| `QDRANT_PATH` | Local storage path |
| `QDRANT_API_KEY` | Qdrant Cloud API key |
| `RAG_ENABLED` | Default: `true` |
| `RAG_TOP_K` | Chunks retrieved per query (default: `6`) |

### Email

| Variable | Description |
|----------|-------------|
| `EMAIL_PROVIDER` | `auto`, `gmail`, `resend`, or `smtp` |
| `GMAIL_*` | Gmail API OAuth credentials |
| `RESEND_API_KEY` / `RESEND_FROM` | Resend HTTPS email |
| `SMTP_*` | Traditional SMTP |

---

## API Overview

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | — | Health + email provider status |
| `GET` | `/config` | Optional | Models, tiers, availability |
| `POST` | `/auth/register` | — | Start registration (email verify) |
| `POST` | `/auth/login` | — | Login → JWT |
| `POST` | `/auth/verify-email` | — | Complete registration |
| `POST` | `/auth/forgot-password` | — | Request reset link |
| `POST` | `/auth/reset-password` | — | Reset password |
| `GET` | `/users/me` | JWT | Current user |
| `PATCH` | `/users/me` | JWT | Update profile |
| `GET` | `/chats` | JWT / guest | List chats |
| `POST` | `/chats/{id}/messages` | JWT / guest | Send message (**SSE stream**) |
| `GET` | `/chat-folders` | JWT | List folders |
| `GET` | `/additional-data` | JWT / guest | Knowledge bases |
| `POST` | `/documents/parse-pdf` | JWT / guest | Parse PDF upload |
| `GET` | `/admin/stats` | Admin | Platform statistics |

Full docs: http://localhost:8000/docs

---

## Models & Tiers

### Subscription tiers

| Tier | Token limit / thread | Models | Web search |
|------|----------------------|--------|------------|
| **Basic** (guest) | 20,000 | GPT-4o Mini only | No |
| **Free** | 60,000 | All available | No |
| **Plus** | 300,000 | All available | Yes |

### Model availability

`GET /config` returns `available: true/false` per model based on configured API keys. Unavailable models are rejected at `POST /chats/{id}/messages` with HTTP 503.

---

## Email Setup

### Gmail API (recommended when SMTP is blocked)

```powershell
pip install google-auth-oauthlib
python scripts/gmail_authorize.py
```

Add the printed `GMAIL_REFRESH_TOKEN` to `.env`.

### Resend

```env
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_...
```

---

## Development

```powershell
# Hot reload
python -m uvicorn app.main:app --reload --port 8000

# Test email delivery
python scripts/test_email.py
```

- Database migrations run automatically on startup via `db_init.py`
- Local SQLite DB: `chatbot.db`
- Local Qdrant data: `qdrant_data/` (gitignored)

---

## Related

- [Root README](../README.md) — full project overview
- [Frontend README](../Frontend/README.md) — Next.js UI
