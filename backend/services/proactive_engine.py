"""
EDITH Feature 2 — Proactive "Know-When-to-Help" Engine
=======================================================
EDITH watches the user's cognitive state and interjects BEFORE they ask.

Trigger Model:
  Eye tracking → fixation_duration + pupil_dilation → cognitive_load_score
  CV camera    → scene_context (task, machinery, document, whiteboard…)
  Calendar     → upcoming_event context
  Together     → decide whether to activate Support Mode

Support Modes:
  TUTORIAL   → step-by-step overlay for machinery/recipe/code
  SIMPLIFY   → reduce HUD complexity when overwhelmed
  REMINDER   → surface calendar event before user notices
  ALERT      → object moved / battery low / unknown person
  IDLE       → proactively summarise day when user is idle
"""

import os, json, logging, time, asyncio
from collections import deque
from typing import Optional
import httpx

log = logging.getLogger("EDITH.Proactive")

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")


class CognitiveLoadMonitor:
    """
    Sliding-window analysis of eye-tracking signals.
    Produces a real-time cognitive load score (0.0–1.0).
    """

    WINDOW = 60          # samples at ~10/s = 6 second window
    HIGH_LOAD_THRESH  = 0.68
    CONFUSED_FIXATION = 2500   # ms staring at same spot = confusion
    BLINK_RATE_NORMAL = 15     # blinks/min

    def __init__(self):
        self._fixation_dur:    deque = deque(maxlen=self.WINDOW)
        self._pupil_dilation:  deque = deque(maxlen=self.WINDOW)
        self._blink_times:     deque = deque(maxlen=30)
        self._last_target:     str   = ""
        self._target_start:    float = 0.0
        self._last_load:       float = 0.0

    def push(self, fixation_duration_ms: int, pupil: float,
             is_blink: bool, gaze_target: str) -> float:
        """Feed one eye-tracking sample, return current load score."""
        now = time.time()
        self._fixation_dur.append(min(fixation_duration_ms, 5000) / 5000)
        self._pupil_dilation.append(max(0.0, min(1.0, pupil)))
        if is_blink:
            self._blink_times.append(now)

        # Blink rate (abnormally low = high concentration/stress)
        recent_blinks = sum(1 for t in self._blink_times if now - t < 60)
        blink_score   = max(0.0, 1.0 - recent_blinks / self.BLINK_RATE_NORMAL)

        if len(self._fixation_dur) < 10:
            return 0.0

        avg_fix    = sum(self._fixation_dur)   / len(self._fixation_dur)
        avg_pupil  = sum(self._pupil_dilation) / len(self._pupil_dilation)
        load_score = avg_fix * 0.45 + avg_pupil * 0.35 + blink_score * 0.20

        self._last_load = round(load_score, 3)
        return self._last_load

    @property
    def is_overloaded(self) -> bool:
        return self._last_load >= self.HIGH_LOAD_THRESH

    @property
    def is_confused(self) -> bool:
        """High fixation on single target = confusion."""
        if not self._fixation_dur:
            return False
        return (list(self._fixation_dur)[-1] > 0.5 and  # long fixation
                self._last_load > 0.55)

    @property
    def load(self) -> float:
        return self._last_load


class ProactiveEngine:
    """
    Watches user state and fires proactive interventions.
    Implements the Trigger Model from the research spec.
    """

    COOLDOWN_S = 30          # minimum seconds between proactive interruptions
    IDLE_AFTER = 120         # seconds of inactivity before idle mode

    def __init__(self):
        self._load_monitor  = CognitiveLoadMonitor()
        self._http = httpx.AsyncClient(timeout=15.0,
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                     "HTTP-Referer": "https://edith-ar.local"})
        self._last_trigger: float = 0.0
        self._last_activity: float = time.time()
        self._pending_triggers: deque = deque(maxlen=5)
        self._suppressed: set = set()   # don't repeat same intervention
        log.info("ProactiveEngine ready")

    def push_gaze(self, fixation_ms: int, pupil: float,
                  is_blink: bool, target: str) -> float:
        """Update cognitive state. Returns current load score."""
        self._last_activity = time.time()
        return self._load_monitor.push(fixation_ms, pupil, is_blink, target)

    def mark_activity(self):
        self._last_activity = time.time()

    async def evaluate(self, gaze_target: str, scene_context: str = "",
                       image_b64: str = None) -> Optional[dict]:
        """
        Main decision loop — call this at 1–2 fps from the WS handler.
        Returns an intervention dict if EDITH should speak up, else None.
        """
        now = time.time()

        # Respect cooldown
        if now - self._last_trigger < self.COOLDOWN_S:
            return None

        load = self._load_monitor.load

        # ── Case 1: User confused (high fixation + high load) ──────────
        if self._load_monitor.is_confused and gaze_target:
            key = f"confused:{gaze_target}"
            if key not in self._suppressed:
                intervention = await self._build_tutorial(gaze_target, image_b64, load)
                if intervention:
                    self._fire(key)
                    return intervention

        # ── Case 2: Cognitive overload → simplify HUD ─────────────────
        if self._load_monitor.is_overloaded:
            key = "overload"
            if key not in self._suppressed:
                self._fire(key)
                return {
                    "type":    "simplify_hud",
                    "mode":    "minimal",
                    "speech":  "You seem overwhelmed. I'm simplifying the display.",
                    "hud_cmd": "set_minimal_mode",
                    "load":    load,
                }

        # ── Case 3: User idle → daily briefing ────────────────────────
        idle_s = now - self._last_activity
        if idle_s > self.IDLE_AFTER:
            key = "idle_briefing"
            if key not in self._suppressed:
                self._fire(key)
                return {
                    "type":   "idle_briefing",
                    "speech": "You've been idle for a while. Want a quick summary of your day?",
                    "action": "daily_briefing",
                }

        return None

    async def _build_tutorial(self, target: str, image_b64: str,
                               load: float) -> Optional[dict]:
        """Ask LLM to generate step-by-step help for the gazed object."""
        if not OPENROUTER_KEY:
            return None
        try:
            content = [{"type": "text",
                        "text": (f"The user is staring at '{target}' with confusion "
                                 f"(cognitive load={load:.2f}). "
                                 "Generate 3–4 concise step-by-step instructions to help them. "
                                 "Return JSON: {\"title\":\"...\",\"steps\":[\"...\"],"
                                 "\"speech\":\"brief spoken intro\"}")}]
            if image_b64:
                content.insert(0, {"type": "image_url",
                                   "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
            r = await self._http.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={"model": "google/gemini-2.0-flash",
                      "messages": [{"role":"user","content":content}],
                      "max_tokens": 300}
            )
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = raw.replace("```json","").replace("```","").strip()
            data = json.loads(raw)
            return {
                "type":    "tutorial_overlay",
                "title":   data.get("title","How-To"),
                "steps":   data.get("steps",[]),
                "speech":  data.get("speech","Let me help you with that."),
                "target":  target,
                "load":    load,
            }
        except Exception as e:
            log.error(f"Tutorial build error: {e}")
            return None

    def _fire(self, key: str):
        self._last_trigger = time.time()
        self._suppressed.add(key)
        # Let intervention repeat after 5 minutes
        asyncio.get_event_loop().call_later(300, lambda: self._suppressed.discard(key))

    def reset_suppression(self):
        self._suppressed.clear()

    @property
    def state(self) -> dict:
        return {
            "load":        self._load_monitor.load,
            "overloaded":  self._load_monitor.is_overloaded,
            "confused":    self._load_monitor.is_confused,
            "idle_s":      round(time.time() - self._last_activity),
        }
