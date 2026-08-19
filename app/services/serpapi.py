import httpx

from app.config import settings


async def search_web(query: str, max_results: int = 5) -> list[dict]:
    if not settings.serpapi_api_key:
        return []

    params = {
        "q": query,
        "api_key": settings.serpapi_api_key,
        "engine": "google",
        "num": max_results,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get("https://serpapi.com/search", params=params)
        response.raise_for_status()
        data = response.json()

    results = []
    for item in data.get("organic_results", [])[:max_results]:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
        )
    return results


def build_search_context(results: list[dict]) -> str:
    if not results:
        return "No web search results found."

    lines = ["Use the following web search results to answer the question. Cite sources when relevant.\n"]
    for i, result in enumerate(results, 1):
        lines.append(f"[{i}] {result['title']}")
        lines.append(f"URL: {result['url']}")
        lines.append(f"Snippet: {result['snippet']}\n")
    return "\n".join(lines)
