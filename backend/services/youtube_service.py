"""
EDITH YouTube Service
=====================
Searches YouTube and returns embeddable URLs for MLWebView.
Tries YouTube Data API v3 first, scrapes as fallback (no key needed).
"""
import os, logging, re
import urllib.parse
import httpx

log = logging.getLogger("EDITH.YouTube")
YT_KEY = os.getenv("YOUTUBE_API_KEY", "")


class YouTubeService:
    def __init__(self):
        self._http  = httpx.AsyncClient(timeout=10.0)
        self._queue: list = []
        log.info(f"YouTubeService | key={'SET' if YT_KEY else 'missing→scraping'}")

    async def find_and_play(self, query: str) -> dict:
        results = await self.search(query, max_results=1)
        if results:
            self._queue.insert(0, results[0])
            return results[0]
        return {"title": "Not found", "video_id": "", "embed_url": "", "url": ""}

    async def search(self, query: str, max_results: int = 5) -> list:
        if YT_KEY:
            try:
                return await self._api_search(query, max_results)
            except Exception as e:
                log.warning(f"YT API failed: {e} — falling back to scrape")
        return await self._scrape_search(query, max_results)

    async def _api_search(self, query: str, n: int) -> list:
        r = await self._http.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"key": YT_KEY, "q": query, "part": "snippet",
                    "type": "video", "maxResults": n},
        )
        r.raise_for_status()
        return [self._fmt(i) for i in r.json().get("items", [])]

    async def _scrape_search(self, query: str, n: int) -> list:
        q = urllib.parse.quote_plus(query)
        r = await self._http.get(
            f"https://www.youtube.com/results?search_query={q}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"},
        )
        ids    = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text)
        titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"', r.text)
        seen, results = set(), []
        for vid, title in zip(ids, titles):
            if vid not in seen:
                seen.add(vid)
                results.append(self._make(vid, title))
            if len(results) >= n:
                break
        return results

    def _fmt(self, item: dict) -> dict:
        vid = item["id"]["videoId"]
        return self._make(vid, item["snippet"]["title"],
                          item["snippet"].get("channelTitle", ""))

    def _make(self, vid: str, title: str, channel: str = "") -> dict:
        return {
            "video_id":  vid,
            "title":     title,
            "channel":   channel,
            "thumbnail": f"https://img.youtube.com/vi/{vid}/mqdefault.jpg",
            "url":       f"https://www.youtube.com/watch?v={vid}",
            "embed_url": f"https://www.youtube.com/embed/{vid}?autoplay=1&controls=1",
        }

    def get_queue(self) -> list:
        return self._queue

    def clear_queue(self):
        self._queue.clear()
