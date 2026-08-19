import json


def parse_api_error(body: str, provider: str = "API") -> str:
    if not body:
        return f"{provider} request failed"
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return body[:500]

    err = data.get("error")
    if not isinstance(err, dict):
        return body[:500]

    code = err.get("code", "")
    message = err.get("message") or body[:500]

    if code == "unsupported_country_region_territory":
        return (
            "OpenAI blocked requests from this server's region or IP "
            "(common on VPS/cloud hosts). Set GPT_PROVIDER=openrouter in .env and add "
            "OPENROUTER_API_KEY, or run the backend from a supported network."
        )

    return message


def is_region_blocked_message(message: str) -> bool:
    lower = message.lower()
    return (
        "unsupported_country_region_territory" in lower
        or "country, region, or territory not supported" in lower
        or "blocked requests from this server's region" in lower
    )
