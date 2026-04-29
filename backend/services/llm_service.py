"""
EDITH LLM Service — OpenRouter Intelligence Gateway
====================================================
Dynamic model routing:
  Intent classification → llama-3.1-8b-instruct   (fast, cheap)
  Chat / reasoning     → claude-sonnet-4-5          (smart)
  Vision / long ctx    → gemini-2.0-flash           (multimodal, 2M ctx)
  Fallback             → mistral-7b-instruct         (always available)
"""
import os, json, logging, asyncio
from typing import AsyncGenerator
import httpx

log = logging.getLogger("EDITH.LLM")

KEY  = os.getenv("OPENROUTER_API_KEY", "")
BASE = "https://openrouter.ai/api/v1"

M_FAST    = "meta-llama/llama-3.1-8b-instruct"
M_SMART   = "anthropic/claude-sonnet-4-5"
M_VISION  = "google/gemini-2.0-flash"
M_FALLBACK= "mistralai/mistral-7b-instruct"

SYSTEM = """You are E.D.I.T.H — Even Dead I'm The Hero — an advanced AR AI assistant 
on Magic Leap 2 glasses. You are precise, helpful, and concise (2–3 sentences max for 
AR display). You have access to Gmail, YouTube, web search, and the user's spatial 
environment. Respond like JARVIS: confident, occasionally witty, always useful."""

INTENT_SYSTEM = """Classify this voice/text command into exactly one intent. Return ONLY valid JSON.

Intents: web_search, play_youtube, read_email, send_email, summarize_email,
         identify_object, weather, set_reminder, translate, system_status,
         navigate, anchor_content, swarm_briefing, spatial_query,
         meeting_summary, biometrics, predict, aoi_scan, whatsapp,
         privacy_scan, translate_live, general_chat

JSON format: {"intent": "<intent>", "params": {<relevant key-value pairs>}}

param keys by intent:
  web_search      → {"query": "..."}
  play_youtube    → {"query": "video title or topic"}
  read_email      → {"count": 5, "filter": "unread|important|all"}
  send_email      → {"to": "name or email", "subject": "...", "body_hint": "..."}
  identify_object → {"object": "gaze target"}
  weather         → {"location": "city or current"}
  set_reminder    → {"reminder": "...", "time": "in X minutes/at HH:MM"}
  translate       → {"text": "...", "language": "..."}
  navigate        → {"destination": "..."}
  anchor_content  → {"label": "...", "content_type": "note|search|email"}
  swarm_briefing  → {"query": "full user request for multi-agent processing"}
  spatial_query   → {"query": "where is X / what was on Y"}
  meeting_summary → {}
  biometrics      → {}
  predict         → {}
  aoi_scan        → {"object": "gaze target label"}
  whatsapp        → {"action": "check|send", "to": "phone or name", "text": "message"}
  privacy_scan    → {}
  translate_live  → {"action": "start|stop", "language": "target language"}
  general_chat    → {}

Use swarm_briefing for complex multi-part requests like "prep for my meeting" or "brief me on my day".
Use spatial_query for "where did I put X" or "what was on the whiteboard".
Use biometrics for "heart rate", "stress level", "how am I doing".
Use predict for "what should I do next" or "what do I usually do now".
Use aoi_scan for "what can I do with this" or "what are my options" (when gazing at object).
Use whatsapp for "WhatsApp messages", "message from X", "send WhatsApp to Y".
Use privacy_scan for "any cameras", "is anyone recording", "privacy check".
Use translate_live for "translate what they're saying", "live subtitles", "start translation".
Consider gaze context heavily. Return nothing except valid JSON."""


class LLMService:
    def __init__(self):
        self._http = httpx.AsyncClient(
            base_url=BASE,
            headers={"Authorization": f"Bearer {KEY}",
                     "HTTP-Referer": "https://edith-ar.local",
                     "X-Title": "EDITH AR",
                     "Content-Type": "application/json"},
            timeout=30.0,
        )
        log.info(f"LLMService ready | key={'SET' if KEY else 'MISSING — set OPENROUTER_API_KEY'}")

    # ── Intent classification ─────────────────────────────────────────────────

    async def classify_intent(self, text: str, gaze: str = None,
                               history: list = None, pupil_load: float = None) -> dict:
        hint = f"\nGaze target: {gaze}" if gaze else ""
        if pupil_load and pupil_load > 0.7:
            hint += "\n[cognitive load HIGH — keep response simple]"
        prompt = f"{hint}\nCommand: \"{text}\""
        try:
            raw = await self._call(M_FAST, INTENT_SYSTEM, prompt, max_tokens=200, temp=0.1)
            raw = raw.strip().replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
        except Exception as e:
            log.warning(f"Intent classification failed ({e}) — defaulting to general_chat")
            return {"intent": "general_chat", "params": {}}

    # ── Chat ─────────────────────────────────────────────────────────────────

    async def chat(self, text: str, history: list = None) -> str:
        msgs = list(history or []) + [{"role": "user", "content": text}]
        return await self._call(M_SMART, SYSTEM, messages=msgs, max_tokens=300, temp=0.7)

    async def chat_stream(self, text: str, history: list = None) -> AsyncGenerator[str, None]:
        msgs = [{"role": "system", "content": SYSTEM}]
        msgs += list(history or [])
        msgs.append({"role": "user", "content": text})
        async with self._http.stream("POST", "/chat/completions",
                                     json={"model": M_SMART, "messages": msgs,
                                           "max_tokens": 300, "stream": True}) as r:
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        token = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                        if token:
                            yield token
                    except Exception:
                        pass

    # ── Summaries ─────────────────────────────────────────────────────────────

    async def summarize_search(self, query: str, results: list) -> str:
        snips = "\n".join(f"- {r.get('title','')}: {r.get('snippet','')}" for r in results[:5])
        p = f"User asked: '{query}'\n\nResults:\n{snips}\n\nSummarise in 2 sentences for AR."
        return await self._call(M_SMART, SYSTEM, p, max_tokens=150, temp=0.3)

    async def summarize_emails(self, emails: list) -> str:
        text = "\n".join(
            f"From: {e.get('from','?')} | Subject: {e.get('subject','?')} | {e.get('snippet','')}"
            for e in emails[:5]
        )
        p = f"Recent emails:\n{text}\n\nTwo-sentence summary of what needs attention."
        return await self._call(M_VISION, SYSTEM, p, max_tokens=200, temp=0.3)

    async def deep_summarize_emails(self, emails: list) -> str:
        text = "\n\n".join(
            f"From: {e.get('from','?')}\nSubject: {e.get('subject','?')}\n{e.get('snippet','')}"
            for e in emails
        )
        p = f"All emails:\n{text}\n\nExecutive summary: what is urgent, what can wait? 3 sentences."
        return await self._call(M_VISION, SYSTEM, p, max_tokens=300, temp=0.2)

    async def draft_email(self, user_request: str, params: dict) -> dict:
        p = (f"Draft email based on: '{user_request}'\nParams: {json.dumps(params)}\n"
             "Return JSON only: {\"to\":\"...\",\"subject\":\"...\",\"body\":\"...\"}")
        raw = await self._call(M_SMART, SYSTEM, p, max_tokens=400, temp=0.4)
        try:
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
        except Exception:
            return {"to": params.get("to", ""), "subject": "Message", "body": raw}

    async def translate(self, text: str, language: str) -> str:
        return await self._call(M_FAST, None,
                                f"Translate to {language}: \"{text}\"\nReturn translation only.",
                                max_tokens=200, temp=0.1)

    async def assess_spatial_context(self, target: str, spatial: dict = None) -> dict:
        p = (f"Spatial target: {target}\nData: {json.dumps(spatial or {})}\n"
             "Environmental awareness assessment as EDITH. "
             "Return JSON: {\"summary\":\"...\",\"risk\":\"low|medium|high\","
             "\"points_of_interest\":[],\"recommended_actions\":[]}")
        raw = await self._call(M_SMART, SYSTEM, p, max_tokens=300, temp=0.3)
        try:
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
        except Exception:
            return {"summary": raw, "risk": "low", "points_of_interest": [],
                    "recommended_actions": []}

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _call(self, model: str, system: str = None, user: str = None,
                    messages: list = None, max_tokens: int = 300, temp: float = 0.7) -> str:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        if messages:
            msgs.extend(messages)
        if user and not messages:
            msgs.append({"role": "user", "content": user})

        for mdl in [model, M_FALLBACK]:
            try:
                r = await self._http.post("/chat/completions",
                                          json={"model": mdl, "messages": msgs,
                                                "max_tokens": max_tokens,
                                                "temperature": temp})
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                log.warning(f"LLM {mdl} failed: {e}")
                if mdl == M_FALLBACK:
                    return "I'm having trouble connecting to my intelligence core. Please try again."
                await asyncio.sleep(0.3)
        return "System error."
