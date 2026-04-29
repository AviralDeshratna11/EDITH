"""
EDITH Novel Feature 6 — Predictive Context Engine
==================================================
EDITH anticipates what you'll need BEFORE you ask,
based on:
  - Time of day patterns (you always check emails at 9am)
  - Calendar events (meeting in 10min → pre-brief you)
  - Location context (entering lab → load lab equipment docs)
  - Recent command history (repeated searches = surface automatically)
  - Biometric state (tired in afternoon → suggest break)

This is what separates an assistant from a COMPANION.
The companion acts; the assistant waits to be asked.
"""

import os, json, logging, time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional
import httpx

log = logging.getLogger("EDITH.Predict")
KEY = os.getenv("OPENROUTER_API_KEY","")


class PredictiveContextEngine:

    def __init__(self):
        self._command_history: list = []        # [{cmd, time, intent, hour}]
        self._location_history: list = []       # [{location, time}]
        self._pattern_cache: dict = {}
        self._http = httpx.AsyncClient(timeout=15.0,
            headers={"Authorization":f"Bearer {KEY}",
                     "HTTP-Referer":"https://edith-ar.local"})
        log.info("PredictiveContextEngine ready")

    def record_command(self, text: str, intent: str):
        now = datetime.now()
        self._command_history.append({
            "text": text, "intent": intent,
            "timestamp": time.time(),
            "hour": now.hour, "weekday": now.weekday(),
        })
        # Keep last 200 commands
        if len(self._command_history) > 200:
            self._command_history = self._command_history[-200:]

    def record_location(self, label: str):
        self._location_history.append({"label": label, "timestamp": time.time()})
        if len(self._location_history) > 100:
            self._location_history = self._location_history[-100:]

    async def predict_next(self, current_hour: int = None,
                            current_location: str = "",
                            bpm: float = None,
                            upcoming_events: list = None) -> Optional[dict]:
        """
        Returns a proactive suggestion based on patterns + context.
        """
        if current_hour is None:
            current_hour = datetime.now().hour

        # ── Pattern: time-based command habits ────────────────────────
        if self._command_history:
            hour_intents = [c["intent"] for c in self._command_history
                            if abs(c["hour"] - current_hour) <= 1]
            if hour_intents:
                most_common = Counter(hour_intents).most_common(1)[0]
                if most_common[1] >= 2:   # done at least twice at this hour
                    intent, count = most_common
                    return {
                        "type":       "predicted_intent",
                        "intent":     intent,
                        "confidence": min(0.95, count / 5),
                        "speech":     f"Based on your patterns, you usually {intent.replace('_',' ')} around this time. Want me to do that?",
                        "action":     intent,
                        "reason":     f"You've done this {count} times at {current_hour}:00",
                    }

        # ── Calendar: meeting in < 15 minutes ─────────────────────────
        if upcoming_events:
            now_ts = time.time()
            for event in upcoming_events:
                try:
                    event_time = datetime.fromisoformat(event.get("start",""))
                    delta_min  = (event_time.timestamp() - now_ts) / 60
                    if 0 < delta_min < 15:
                        return {
                            "type":    "meeting_alert",
                            "event":   event["title"],
                            "minutes": round(delta_min),
                            "speech":  f"Heads up — '{event['title']}' starts in {round(delta_min)} minutes. Want a briefing?",
                            "action":  "swarm_briefing",
                            "query":   f"prep for meeting: {event['title']}",
                        }
                except Exception:
                    pass

        # ── Biometric: tired → suggest break ─────────────────────────
        if bpm and bpm > 95:
            return {
                "type":   "health_alert",
                "bpm":    bpm,
                "speech": f"Your heart rate is elevated at {bpm:.0f} bpm. Consider taking a short break.",
                "action": None,
            }

        # ── Location: new environment → load context ──────────────────
        if current_location and self._location_history:
            last_loc = self._location_history[-1]["label"]
            if current_location != last_loc:
                self.record_location(current_location)
                return {
                    "type":     "location_context",
                    "location": current_location,
                    "speech":   f"You've moved to {current_location}. Want me to pull up anything relevant?",
                    "action":   "web_search",
                    "query":    f"information about {current_location}",
                }

        return None

    def get_daily_summary_topics(self) -> list:
        """Surface the most-used topics from today for the morning brief."""
        today = datetime.now().date()
        today_cmds = [c for c in self._command_history
                      if datetime.fromtimestamp(c["timestamp"]).date() == today]
        topics = Counter(c["intent"] for c in today_cmds)
        return [{"intent": k, "count": v} for k, v in topics.most_common(5)]
