"""
EDITH Feature: Augmented Object Intelligence (AOI)
===================================================
Transforms any physical object into a digital portal with a radial
action menu of contextual affordances.

Pipeline:
  1. Gaze fixation on object (>800ms) → trigger AOI scan
  2. Crop camera frame to gaze bounding box
  3. Send to OpenRouter vision model → get object identity + affordances
  4. Return radial menu items for the HUD to render
  5. User voice-selects or gaze-selects an action

Examples:
  Printer  → [Print last attachment] [Check ink levels] [Order ink]
  Laptop   → [Screen share] [Open last file] [Check battery]
  Whiteboard → [Capture & OCR] [Email photo] [Set as anchor]
  Coffee maker → [Start brew] [How to clean] [Order pods]
  Person   → [Show recent emails] [Start translation] [Call them]
"""

import os, json, logging, time, base64
from typing import Optional
import httpx

log = logging.getLogger("EDITH.AOI")
KEY   = os.getenv("OPENROUTER_API_KEY", "")
MODEL = "google/gemini-2.0-flash"

# Affordance database — pre-defined actions per object category
# Extended at runtime via LLM for unknown objects
AFFORDANCE_DB: dict[str, list[dict]] = {
    "printer": [
        {"id": "print_email",  "label": "Print last email",    "icon": "📄", "action": "print_gmail_attachment"},
        {"id": "check_ink",    "label": "Check ink",           "icon": "🖨", "action": "web_search:printer ink levels check"},
        {"id": "order_ink",    "label": "Order ink",           "icon": "🛒", "action": "web_search:buy printer ink cartridge"},
        {"id": "fix_jam",      "label": "Fix paper jam",       "icon": "🔧", "action": "web_search:how to fix paper jam"},
    ],
    "laptop": [
        {"id": "battery",      "label": "Battery status",      "icon": "🔋", "action": "system_status"},
        {"id": "open_file",    "label": "Open last file",      "icon": "📂", "action": "spatial_query:last file I was working on"},
        {"id": "screen_share", "label": "Screen share",        "icon": "📡", "action": "web_search:screen share options"},
    ],
    "whiteboard": [
        {"id": "ocr",          "label": "Read & capture",      "icon": "👁", "action": "identify_object"},
        {"id": "email_photo",  "label": "Email this",          "icon": "📧", "action": "send_email:whiteboard contents"},
        {"id": "set_anchor",   "label": "Pin note here",       "icon": "📌", "action": "anchor_content"},
    ],
    "coffee_maker": [
        {"id": "how_to",       "label": "How to use",          "icon": "❓", "action": "web_search:how to use coffee maker"},
        {"id": "clean",        "label": "Cleaning guide",      "icon": "🧹", "action": "web_search:coffee maker cleaning steps"},
        {"id": "order_pods",   "label": "Order pods",          "icon": "🛒", "action": "web_search:buy coffee pods"},
    ],
    "person": [
        {"id": "translate",    "label": "Live translate",      "icon": "🌐", "action": "spatial_translation"},
        {"id": "email_them",   "label": "Email them",          "icon": "📧", "action": "send_email"},
        {"id": "biometrics",   "label": "Read vitals",         "icon": "💓", "action": "biometrics"},
    ],
    "phone": [
        {"id": "messages",     "label": "WhatsApp msgs",       "icon": "💬", "action": "whatsapp_check"},
        {"id": "share",        "label": "Share to phone",      "icon": "📲", "action": "web_search:share to phone"},
    ],
    "book": [
        {"id": "summary",      "label": "Summarise",           "icon": "📚", "action": "identify_object"},
        {"id": "buy",          "label": "Buy online",          "icon": "🛒", "action": "web_search:buy this book"},
        {"id": "reviews",      "label": "Reviews",             "icon": "⭐", "action": "web_search:book review"},
    ],
    "monitor": [
        {"id": "cast",         "label": "Cast EDITH HUD",      "icon": "📡", "action": "web_search:cast screen options"},
        {"id": "brightness",   "label": "Adjust display",      "icon": "☀", "action": "web_search:monitor settings"},
    ],
}

# Object category aliases (maps vision model label → affordance key)
CATEGORY_MAP = {
    "computer": "laptop", "macbook": "laptop", "notebook": "laptop",
    "espresso machine": "coffee_maker", "kettle": "coffee_maker",
    "display": "monitor", "screen": "monitor", "tv": "monitor",
    "writing board": "whiteboard", "chalkboard": "whiteboard",
    "human": "person", "face": "person", "man": "person", "woman": "person",
    "smartphone": "phone", "iphone": "phone", "android": "phone",
    "novel": "book", "textbook": "book", "magazine": "book",
}


class AOIService:
    """Augmented Object Intelligence — turns gaze targets into action portals."""

    def __init__(self):
        self._http = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            headers={"Authorization": f"Bearer {KEY}",
                     "HTTP-Referer": "https://edith-ar.local",
                     "X-Title": "EDITH AOI"},
            timeout=15.0,
        )
        self._cache: dict[str, dict] = {}   # label → {affordances, ts}
        self._scan_cooldown: dict[str, float] = {}
        log.info("AOIService ready")

    async def scan(self, image_b64: str, gaze_hint: str,
                   session_id: str = "default") -> dict:
        """
        Full AOI pipeline: identify object + return radial menu affordances.
        Cached per object label for 60 seconds to avoid repeated API calls.
        """
        now = time.time()

        # Cooldown: don't re-scan same target within 5s
        if gaze_hint in self._scan_cooldown:
            if now - self._scan_cooldown[gaze_hint] < 5.0:
                cached = self._cache.get(gaze_hint)
                if cached:
                    return cached

        # Step 1: Identify the object
        identity = await self._identify(image_b64, gaze_hint)
        label    = identity.get("label", gaze_hint).lower()
        category = self._resolve_category(label)

        # Step 2: Get affordances (from DB or LLM)
        if category in AFFORDANCE_DB:
            affordances = AFFORDANCE_DB[category]
        else:
            affordances = await self._llm_affordances(label, image_b64, identity)

        # Step 3: Get real-time status if possible
        status = await self._get_status(label, identity)

        result = {
            "label":       identity.get("label", gaze_hint),
            "category":    category,
            "description": identity.get("description", ""),
            "confidence":  identity.get("confidence", 0.8),
            "affordances": affordances[:6],   # max 6 items in radial menu
            "status":      status,
            "speech":      self._build_speech(label, affordances, status),
            "hud_data": {
                "type":        "aoi_radial",
                "label":       identity.get("label", gaze_hint),
                "description": identity.get("description",""),
                "affordances": affordances[:6],
                "status":      status,
                "category":    category,
            }
        }

        self._cache[gaze_hint] = result
        self._scan_cooldown[gaze_hint] = now
        return result

    async def _identify(self, image_b64: str, hint: str) -> dict:
        if not image_b64 or not KEY:
            return {"label": hint, "description": "", "confidence": 0.6}
        try:
            content = [
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": (
                    f"Gaze target hint: '{hint}'. "
                    "Identify the primary object. Be specific (brand/model if visible). "
                    'Return JSON only: {"label":"Canon PIXMA printer",'
                    '"description":"inkjet printer, power light on",'
                    '"brand":"Canon","model":"PIXMA MG3620","confidence":0.95}'
                )}
            ]
            r = await self._http.post("/chat/completions", json={
                "model": MODEL,
                "messages": [{"role":"user","content":content}],
                "max_tokens": 200,
            })
            raw = r.json()["choices"][0]["message"]["content"].strip()
            return json.loads(raw.replace("```json","").replace("```","").strip())
        except Exception as e:
            log.error(f"AOI identify error: {e}")
            return {"label": hint, "description": "", "confidence": 0.5}

    async def _llm_affordances(self, label: str, image_b64: str,
                                identity: dict) -> list[dict]:
        """For unknown objects, ask LLM to generate contextual actions."""
        if not KEY:
            return [{"id":"search","label":"Search online","icon":"🔍","action":f"web_search:{label}"}]
        try:
            prompt = (
                f"Object: {label}\nDescription: {identity.get('description','')}\n\n"
                "Generate 4 useful AR action buttons a user would want for this object.\n"
                'Return JSON array: [{"id":"...","label":"Short label","icon":"emoji","action":"action_type:params"},...]\n'
                "action_type must be one of: web_search, send_email, identify_object, anchor_content, general_chat"
            )
            r = await self._http.post("/chat/completions", json={
                "model": "meta-llama/llama-3.1-8b-instruct",
                "messages": [{"role":"user","content":prompt}],
                "max_tokens": 300,
            })
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = raw.replace("```json","").replace("```","").strip()
            # Find JSON array
            start = raw.find("["); end = raw.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(raw[start:end])
        except Exception as e:
            log.error(f"LLM affordance error: {e}")
        return [
            {"id":"info",   "label":"Get info",    "icon":"ℹ","action":f"web_search:{label}"},
            {"id":"how_to", "label":"How to use",  "icon":"❓","action":f"web_search:how to use {label}"},
            {"id":"buy",    "label":"Buy/replace", "icon":"🛒","action":f"web_search:buy {label}"},
        ]

    async def _get_status(self, label: str, identity: dict) -> Optional[dict]:
        """Get real-time status where available (battery, connectivity, etc.)"""
        desc = identity.get("description","").lower()
        status = {}
        if "power" in desc or "on" in desc:
            status["power"] = "on"
        if "off" in desc:
            status["power"] = "off"
        if "low" in desc or "empty" in desc:
            status["level"] = "low"
        return status if status else None

    def _resolve_category(self, label: str) -> str:
        label = label.lower()
        for key in AFFORDANCE_DB:
            if key in label:
                return key
        for alias, category in CATEGORY_MAP.items():
            if alias in label:
                return category
        return "unknown"

    def _build_speech(self, label: str, affordances: list, status: dict) -> str:
        n     = len(affordances)
        acts  = ", ".join(a["label"] for a in affordances[:3])
        stat  = f" Status: {status}." if status else ""
        return f"I see a {label}.{stat} {n} actions available: {acts}."
