from app.config import settings

BASIC_TOKEN_LIMIT = 20_000
FREE_TOKEN_LIMIT = 60_000
PLUS_TOKEN_LIMIT = 300_000

BASIC_MODEL = "gpt-4o-mini"

ASSISTANT_SYSTEM_PROMPT = """You are a helpful, accurate assistant.

Reply style:
- For short or simple questions, a normal conversational answer is fine.
- When the answer has multiple sections, comparisons, steps, options, or lists, structure it with Markdown:
  - Use ## / ### headings for sections
  - Use bullet (-) or numbered (1.) lists for items—one item per line
  - Use **bold** for key terms
  - Use Markdown tables for side-by-side comparisons
  - Use fenced ```language code blocks for code, SQL, or commands

Keep answers clear and scannable. Do not over-format simple replies."""

OPENAI_MODELS = [
    {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
    {"id": "gpt-4o", "name": "GPT-4o"},
    {"id": "gpt-5.6-luna", "name": "GPT-5.6 Luna"},
]

OPENROUTER_MODELS = [
    {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet"},
    {"id": "google/gemini-pro-1.5", "name": "Gemini Pro 1.5"},
    {"id": "x-ai/grok-beta", "name": "Grok Beta"},
]

AVAILABLE_MODELS = OPENAI_MODELS + OPENROUTER_MODELS

OPENAI_MODEL_IDS = {m["id"] for m in OPENAI_MODELS}

# Map app model IDs → OpenRouter model IDs (for GPT fallback / openrouter provider)
OPENROUTER_MODEL_MAP = {
    "gpt-4o-mini": "openai/gpt-4o-mini",
    "gpt-4o": "openai/gpt-4o",
    "gpt-5.6-luna": "openai/gpt-5.6-luna",
}


def to_openrouter_model(model_id: str) -> str:
    return OPENROUTER_MODEL_MAP.get(model_id, model_id)


def resolve_provider(model_id: str) -> str:
    if model_id not in OPENAI_MODEL_IDS:
        return "openrouter"
    if settings.gpt_provider.lower() == "openrouter":
        return "openrouter"
    return "openai"


def get_model_provider(model_id: str) -> str:
    return resolve_provider(model_id)


MODEL_UNAVAILABLE_MESSAGE = "This model didn't available at this version"


def is_model_available(model_id: str) -> bool:
    has_openai = bool(settings.openai_api_key.strip())
    has_openrouter = bool(settings.openrouter_api_key.strip())
    provider = resolve_provider(model_id)

    if provider == "openrouter":
        return has_openrouter

    if has_openai:
        return True
    return has_openrouter


def is_web_search_available() -> bool:
    return bool(settings.serpapi_api_key.strip())
