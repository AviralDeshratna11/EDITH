"""
EDITH Search Service
====================
Multi-source web search with automatic fallback chain:
  1. Google Custom Search Engine (best quality, needs keys)
  2. SerpAPI (good quality, 100 free/month)
  3. DuckDuckGo Instant Answer API (free, no key, always available)
"""
import os, logging
import httpx

log = logging.getLogger("EDITH.Search")

GOOGLE_SEARCH_KEY = os.getenv("GOOGLE_SEARCH_API_KEY", "")
GOOGLE_CSE_ID     = os.getenv("GOOGLE_CSE_ID", "")
SERPAPI_KEY       = os.getenv("SERPAPI_KEY", "")


class SearchService:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=10.0)
        if GOOGLE_SEARCH_KEY and GOOGLE_CSE_ID:
            log.info("SearchService: Google CSE primary")
        elif SERPAPI_KEY:
            log.info("SearchService: SerpAPI primary")
        else:
            log.info("SearchService: DuckDuckGo (no API keys set — fully functional)")

    async def search(self, query: str, num: int = 5) -> list:
        """Returns list of {title, link, snippet} dicts."""
        for method in [self._google_cse, self._serpapi, self._ddg]:
            try:
                results = await method(query, num)
                if results:
                    log.debug(f"Search '{query}' → {len(results)} results")
                    return results
            except Exception as e:
                log.debug(f"Search method failed: {e}")
        return [{"title": query, "link": "", "snippet": f"Search result for: {query}"}]

    async def _google_cse(self, query: str, num: int) -> list:
        if not (GOOGLE_SEARCH_KEY and GOOGLE_CSE_ID):
            return []
        r = await self._client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": GOOGLE_SEARCH_KEY, "cx": GOOGLE_CSE_ID,
                    "q": query, "num": min(num, 10)},
        )
        r.raise_for_status()
        return [{"title": i.get("title", ""), "link": i.get("link", ""),
                 "snippet": i.get("snippet", "")}
                for i in r.json().get("items", [])]

    async def _serpapi(self, query: str, num: int) -> list:
        if not SERPAPI_KEY:
            return []
        r = await self._client.get(
            "https://serpapi.com/search",
            params={"q": query, "api_key": SERPAPI_KEY, "num": num, "hl": "en"},
        )
        r.raise_for_status()
        return [{"title": i.get("title", ""), "link": i.get("link", ""),
                 "snippet": i.get("snippet", "")}
                for i in r.json().get("organic_results", [])]

    async def _ddg(self, query: str, num: int) -> list:
        """DuckDuckGo — zero configuration needed."""
        r = await self._client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_redirect": 1, "no_html": 1},
            headers={"User-Agent": "EDITH-AR/2.0"},
        )
        data = r.json()
        results = []
        if data.get("Abstract"):
            results.append({"title": data.get("Heading", query),
                             "link": data.get("AbstractURL", ""),
                             "snippet": data.get("Abstract", "")})
        for t in data.get("RelatedTopics", []):
            if isinstance(t, dict) and "Text" in t:
                results.append({"title": t.get("Text", "")[:80],
                                 "link": t.get("FirstURL", ""),
                                 "snippet": t.get("Text", "")})
            if len(results) >= num:
                break
        return results[:num]
