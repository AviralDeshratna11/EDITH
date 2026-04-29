"""EDITH Vision Service — gaze-grounded object ID via OpenRouter multimodal"""
import os, json, logging
import httpx

log = logging.getLogger("EDITH.Vision")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")


class VisionService:
    MODEL = "google/gemini-2.0-flash"

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                     "HTTP-Referer": "https://edith-ar.local",
                     "X-Title": "EDITH Vision"},
            timeout=15.0,
        )
        log.info(f"VisionService ready | model={self.MODEL}")

    async def identify(self, gaze_hint: str, image_b64: str = None) -> dict:
        if image_b64:
            return await self._vision_call(image_b64, gaze_hint)
        return {"label": gaze_hint or "object", "confidence": 0.6, "category": "unknown"}

    async def _vision_call(self, image_b64: str, hint: str) -> dict:
        try:
            r = await self._client.post("/chat/completions", json={
                "model": self.MODEL,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text",
                     "text": (f"Gaze hint: '{hint}'. Identify the PRIMARY object. "
                              'Return JSON only: {"label":"...","confidence":0.9,"category":"..."}')}
                ]}],
                "max_tokens": 150,
            })
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
        except Exception as e:
            log.error(f"Vision error: {e}")
            return {"label": hint or "object", "confidence": 0.5, "category": "unknown"}

    async def ocr(self, image_b64: str) -> str:
        try:
            r = await self._client.post("/chat/completions", json={
                "model": self.MODEL,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text", "text": "Extract all visible text from this image. Return plain text only."}
                ]}],
                "max_tokens": 1000,
            })
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.error(f"OCR error: {e}")
            return "Could not read text."
