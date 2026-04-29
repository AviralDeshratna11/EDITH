"""
EDITH Feature: Affective UI — Cognitive Load Management
========================================================
EDITH monitors pupil dilation via ML2's internal eye cameras and
automatically adapts the interface to match the user's mental state.

Stress Index formula (from research spec):
    Stress_index = Pupil_current / Pupil_baseline

    Where Pupil_baseline is calibrated in the first 30 seconds
    of the session (calm, neutral state).

Response Modes:
  CALM      (index < 1.2) → Full HUD, all panels visible
  ELEVATED  (index 1.2–1.5) → Reduce non-critical notifications
  STRESSED  (index 1.5–1.8) → Minimal HUD, calm voice tone
  OVERLOAD  (index > 1.8) → Emergency simplification, break suggestion

Additional signals:
  - Blink rate < 10/min → extreme concentration
  - Fixation duration > 3s → confusion or difficulty
  - Saccade velocity drops → fatigue

The AI also adjusts its response tone:
  Calm state → normal EDITH tone
  Elevated   → shorter responses, larger text
  Stressed   → only critical info, suggests break
"""

import os, logging, time
from collections import deque
from enum import Enum
import numpy as np

log = logging.getLogger("EDITH.AffectiveUI")


class CognitiveState(Enum):
    CALM      = "calm"
    ELEVATED  = "elevated"
    STRESSED  = "stressed"
    OVERLOAD  = "overload"


# HUD configuration per cognitive state
HUD_CONFIGS = {
    CognitiveState.CALM: {
        "opacity":          1.0,
        "panels_visible":   ["left","centre","right","bottom"],
        "font_scale":       1.0,
        "notification_level":"all",
        "voice_tone":       "normal",
        "hud_mode":         "full",
    },
    CognitiveState.ELEVATED: {
        "opacity":          0.9,
        "panels_visible":   ["left","centre","right","bottom"],
        "font_scale":       1.1,
        "notification_level":"important",
        "voice_tone":       "calm",
        "hud_mode":         "reduced",
    },
    CognitiveState.STRESSED: {
        "opacity":          0.85,
        "panels_visible":   ["centre","bottom"],
        "font_scale":       1.3,
        "notification_level":"critical",
        "voice_tone":       "minimal",
        "hud_mode":         "minimal",
    },
    CognitiveState.OVERLOAD: {
        "opacity":          0.7,
        "panels_visible":   ["centre"],
        "font_scale":       1.5,
        "notification_level":"none",
        "voice_tone":       "emergency",
        "hud_mode":         "emergency",
    },
}


class AffectiveUI:
    """
    Pupil-dilation-based affective computing engine.
    Implements the Stress_index = Pupil_current / Pupil_baseline formula.
    """

    # Calibration window — first N samples establish baseline
    CALIBRATION_N   = 60      # ~6s at 10Hz
    # Sliding window for stress calculation
    WINDOW_SIZE     = 30      # 3 seconds at 10Hz
    # State change hysteresis — avoid rapid toggling
    HYSTERESIS_S    = 8.0

    THRESHOLDS = {
        "elevated": 1.20,
        "stressed": 1.50,
        "overload": 1.80,
    }

    def __init__(self):
        self._calibration: deque = deque(maxlen=self.CALIBRATION_N)
        self._window:      deque = deque(maxlen=self.WINDOW_SIZE)
        self._blink_times: deque = deque(maxlen=40)
        self._fixations:   deque = deque(maxlen=20)

        self._baseline:    float = 0.0
        self._is_calibrated      = False
        self._current_state      = CognitiveState.CALM
        self._last_state_change  = 0.0
        self._stress_history:    deque = deque(maxlen=100)

        log.info("AffectiveUI ready — calibrating baseline pupil diameter")

    def push(self, pupil_left: float, pupil_right: float,
             is_blink: bool = False, fixation_duration_ms: int = 0) -> dict:
        """
        Feed one ML2 eye tracking sample.
        pupil_left / pupil_right: diameter in millimetres (ML2 range: 2.0–8.0mm)

        Returns current affective state dict.
        """
        now   = time.time()
        pupil = (pupil_left + pupil_right) / 2.0

        # Blink tracking
        if is_blink:
            self._blink_times.append(now)

        # Fixation tracking
        if fixation_duration_ms > 0:
            self._fixations.append(fixation_duration_ms)

        # Calibration phase
        if not self._is_calibrated:
            self._calibration.append(pupil)
            if len(self._calibration) >= self.CALIBRATION_N:
                self._baseline     = float(np.median(list(self._calibration)))
                self._is_calibrated = True
                log.info(f"Pupil baseline calibrated: {self._baseline:.2f}mm")
            return self._state_dict(1.0)

        # Compute stress index
        self._window.append(pupil)
        avg_current  = float(np.mean(list(self._window)))
        stress_index = avg_current / max(self._baseline, 0.1)
        self._stress_history.append({"ts": now, "index": stress_index, "pupil": pupil})

        # Blink rate (low = high concentration/stress)
        recent_blinks = sum(1 for t in self._blink_times if now - t < 60)
        # Normal adult blink rate: 15-20/min. Below 10 = concentration.
        blink_stress  = max(0.0, (10 - recent_blinks) / 10) * 0.3

        # Fixation duration stress
        avg_fix       = float(np.mean(list(self._fixations))) if self._fixations else 0
        fix_stress    = min(0.3, avg_fix / 10000)   # 3000ms+ fixation = stressed

        # Combined stress index
        combined      = stress_index + blink_stress + fix_stress

        # State classification with hysteresis
        new_state = self._classify(combined)
        if new_state != self._current_state:
            if (now - self._last_state_change) > self.HYSTERESIS_S:
                old = self._current_state
                self._current_state  = new_state
                self._last_state_change = now
                log.info(f"Cognitive state: {old.value} → {new_state.value} "
                         f"(index={combined:.2f})")

        return self._state_dict(combined)

    def _classify(self, index: float) -> CognitiveState:
        if index >= self.THRESHOLDS["overload"]:
            return CognitiveState.OVERLOAD
        if index >= self.THRESHOLDS["stressed"]:
            return CognitiveState.STRESSED
        if index >= self.THRESHOLDS["elevated"]:
            return CognitiveState.ELEVATED
        return CognitiveState.CALM

    def _state_dict(self, stress_index: float) -> dict:
        state  = self._current_state
        config = HUD_CONFIGS[state]
        return {
            "state":         state.value,
            "stress_index":  round(stress_index, 3),
            "baseline_mm":   round(self._baseline, 2),
            "calibrated":    self._is_calibrated,
            "hud_config":    config,
            "speech_tone":   config["voice_tone"],
            "hud_mode":      config["hud_mode"],
            "message":       self._state_message(state),
        }

    def _state_message(self, state: CognitiveState) -> str:
        return {
            CognitiveState.CALM:     "",
            CognitiveState.ELEVATED: "Slight cognitive elevation detected — reducing clutter.",
            CognitiveState.STRESSED: "You seem stressed. I've simplified the display.",
            CognitiveState.OVERLOAD: "High cognitive load. Take a breath. Only critical info shown.",
        }[state]

    def get_hud_config(self) -> dict:
        return HUD_CONFIGS[self._current_state]

    def reset_calibration(self):
        self._calibration.clear()
        self._is_calibrated = False
        self._baseline = 0.0
        log.info("Pupil baseline reset — recalibrating")

    @property
    def state(self) -> CognitiveState:
        return self._current_state

    @property
    def is_calibrated(self) -> bool:
        return self._is_calibrated

    @property
    def stress_trend(self) -> str:
        """Rising / falling / stable stress over last 30 seconds."""
        recent = [s["index"] for s in list(self._stress_history)[-30:]]
        if len(recent) < 10:
            return "calibrating"
        first_half = np.mean(recent[:len(recent)//2])
        second_half= np.mean(recent[len(recent)//2:])
        delta = second_half - first_half
        if delta > 0.1:   return "rising"
        if delta < -0.1:  return "falling"
        return "stable"


class AffectiveUIService:
    """Multi-session affective UI manager."""

    def __init__(self):
        self._sessions: dict[str, AffectiveUI] = {}
        log.info("AffectiveUIService ready")

    def push(self, session_id: str, pupil_l: float, pupil_r: float,
             is_blink: bool = False, fixation_ms: int = 0) -> dict:
        if session_id not in self._sessions:
            self._sessions[session_id] = AffectiveUI()
        return self._sessions[session_id].push(pupil_l, pupil_r, is_blink, fixation_ms)

    def get_state(self, session_id: str) -> dict:
        if session_id not in self._sessions:
            return {"state": "calm", "calibrated": False}
        s = self._sessions[session_id]
        return s._state_dict(1.0)

    def reset(self, session_id: str):
        if session_id in self._sessions:
            self._sessions[session_id].reset_calibration()
