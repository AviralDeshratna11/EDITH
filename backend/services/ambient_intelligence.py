"""
EDITH Novel Feature 5 — Ambient Audio Intelligence
===================================================
EDITH passively listens to ambient conversations and:
  - Auto-summarises meetings/lectures in real-time
  - Extracts action items and decisions
  - Detects when someone says your name → alerts you
  - Translates foreign language overheard speech in real-time

This runs as a background "always-on" mode (low-power)
distinct from the voice command mode (high-attention).

Also implements:
  - Live captioning overlay (AR subtitles on speakers)
  - Keyword spotting ("EDITH", "hey", your name)
  - Sentiment analysis of overheard conversation
"""

import os, json, logging, time, asyncio
from collections import deque
from typing import Optional
import httpx

log = logging.getLogger("EDITH.Ambient")

KEY = os.getenv("OPENROUTER_API_KEY","")
DG_KEY = os.getenv("DEEPGRAM_API_KEY","")
WAKE_WORDS = {"edith", "hey", "jarvis", "assistant"}
USER_NAME  = os.getenv("USER_NAME","").lower()
if USER_NAME:
    WAKE_WORDS.add(USER_NAME)


class AmbientIntelligence:
    """
    Passive ambient audio processing — runs in background,
    different from the active voice command pipeline.
    """

    TRANSCRIPT_WINDOW = 300     # keep last 5 minutes of transcript
    SUMMARY_EVERY     = 120     # auto-summarise every 2 minutes

    def __init__(self):
        self._transcript: deque = deque(maxlen=200)   # utterances
        self._last_summary      = time.time()
        self._meeting_active    = False
        self._participants: set = set()
        self._action_items: list= []
        self._http = httpx.AsyncClient(timeout=15.0,
            headers={"Authorization":f"Bearer {KEY}",
                     "HTTP-Referer":"https://edith-ar.local"})
        log.info("AmbientIntelligence ready")

    def push_utterance(self, text: str, speaker: str = "unknown",
                       ts: float = None) -> dict:
        """
        Add a transcribed utterance to the ambient buffer.
        Returns any immediate alerts (wake word, name spotted, etc.)
        """
        ts = ts or time.time()
        self._transcript.append({"text":text,"speaker":speaker,"ts":ts})
        if speaker != "unknown":
            self._participants.add(speaker)

        alerts = []
        lower = text.lower()

        # Wake word detection
        for word in WAKE_WORDS:
            if word in lower:
                alerts.append({
                    "type":    "wake_word",
                    "word":    word,
                    "context": text,
                    "speech":  f"I heard '{word}'. Did you need me?",
                })
                break

        # Meeting detection heuristics
        keywords = {"agenda","meeting","action item","follow up","deadline",
                    "decision","proposal","approved","rejected","next steps"}
        if any(k in lower for k in keywords):
            self._meeting_active = True

        return {"alerts": alerts, "meeting_active": self._meeting_active}

    async def get_summary(self, force: bool = False) -> Optional[dict]:
        """
        Generate a meeting/conversation summary.
        Auto-triggers every SUMMARY_EVERY seconds, or on demand.
        """
        now = time.time()
        if not force and (now - self._last_summary) < self.SUMMARY_EVERY:
            return None
        if len(self._transcript) < 3:
            return None

        self._last_summary = now
        transcript_text = "\n".join(
            f"[{t['speaker']}]: {t['text']}" for t in list(self._transcript)[-50:]
        )

        try:
            r = await self._http.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": "meta-llama/llama-3.1-8b-instruct",
                    "messages": [{"role":"user","content":
                        f"Meeting transcript:\n{transcript_text}\n\n"
                        "Extract: 1) 2-sentence summary 2) Action items (bullet list) "
                        "3) Key decisions made.\n"
                        'Return JSON: {"summary":"...","action_items":["..."],"decisions":["..."]}'
                    }],
                    "max_tokens": 400,
                }
            )
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = raw.replace("```json","").replace("```","").strip()
            data = json.loads(raw)
            self._action_items = data.get("action_items",[])
            speech = data.get("summary","")
            return {
                "type":         "meeting_summary",
                "summary":      speech,
                "action_items": data.get("action_items",[]),
                "decisions":    data.get("decisions",[]),
                "participants": list(self._participants),
                "speech":       f"Meeting update: {speech}",
                "hud_data": {
                    "type":         "ambient_summary",
                    "summary":      speech,
                    "action_items": data.get("action_items",[]),
                    "decisions":    data.get("decisions",[]),
                },
            }
        except Exception as e:
            log.error(f"Ambient summary error: {e}")
            return None

    async def translate_utterance(self, text: str, target_lang: str = "English") -> str:
        """Real-time translation of overheard speech for AR subtitle overlay."""
        if not text.strip() or not KEY:
            return text
        try:
            r = await self._http.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": "meta-llama/llama-3.1-8b-instruct",
                    "messages": [{"role":"user","content":
                        f"Translate to {target_lang}: \"{text}\"\nReturn only the translation."}],
                    "max_tokens": 150,
                }
            )
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            return text

    async def detect_sentiment(self, text: str) -> dict:
        """Analyse sentiment of overheard conversation for social awareness."""
        if not KEY:
            return {"sentiment":"neutral","score":0.5}
        try:
            r = await self._http.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": "meta-llama/llama-3.1-8b-instruct",
                    "messages": [{"role":"user","content":
                        f"Sentiment of: \"{text}\"\n"
                        'Return JSON: {"sentiment":"positive|neutral|negative|tense",'
                        '"score":0.8,"alert":false}'}],
                    "max_tokens": 60,
                }
            )
            raw = r.json()["choices"][0]["message"]["content"].strip()
            return json.loads(raw.replace("```json","").replace("```","").strip())
        except Exception:
            return {"sentiment":"neutral","score":0.5,"alert":False}

    def get_action_items(self) -> list:
        return self._action_items

    def clear(self):
        self._transcript.clear()
        self._participants.clear()
        self._action_items.clear()
        self._meeting_active = False

    @property
    def stats(self) -> dict:
        return {
            "utterances":     len(self._transcript),
            "participants":   list(self._participants),
            "meeting_active": self._meeting_active,
            "action_items":   len(self._action_items),
        }
