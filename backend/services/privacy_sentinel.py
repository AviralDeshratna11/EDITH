"""
EDITH Feature: Privacy Sentinel — Stealth Camera Detection
===========================================================
Proactively scans the environment for hidden cameras and smart glasses
(Meta Ray-Bans, TCL NXTWEAR, etc.) that may be recording you.

Detection methods:
  1. Visual silhouette matching — smart glasses have distinct form factors
     (small rectangular lenses, temple cameras, LED indicators)
  2. IR reflection detection — camera lenses produce distinctive circular
     hotspots in near-IR light that appear as bright reflections
  3. AI object classification — send suspicious regions to vision model
     for confirmation

Threat levels:
  GREEN  — no threats detected
  AMBER  — possible recording device (smart glasses nearby)
  RED    — confirmed active camera/recording device detected

HUD Response:
  Green glow → all clear
  Amber wireframe bounding box → potential threat flagged
  Red pulsing wireframe → confirmed threat — consider privacy mode
"""

import os, json, logging, time, base64, io
from typing import Optional
import httpx
import numpy as np

log = logging.getLogger("EDITH.Privacy")
KEY   = os.getenv("OPENROUTER_API_KEY", "")
MODEL = "google/gemini-2.0-flash"

# Known smart glasses / recording device visual signatures
THREAT_SIGNATURES = [
    "ray-ban meta smart glasses", "meta ray-ban", "spectacles snap",
    "tcl nxtwear", "rokid max", "xreal air", "vuzix blade",
    "camera lens", "webcam", "security camera", "cctv", "surveillance camera",
    "ring doorbell", "google nest cam", "hidden camera",
    "recording led", "red recording light", "camera indicator",
]

# Threat keywords that trigger RED alert
RED_KEYWORDS = {
    "camera", "lens", "webcam", "cctv", "surveillance", "recording",
    "hidden", "spy", "security camera", "ring", "nest"
}
# Amber keywords
AMBER_KEYWORDS = {
    "smart glasses", "ar glasses", "xr glasses", "wearable", "glasses",
    "led light", "indicator light"
}


class PrivacySentinel:
    """
    Real-time privacy threat detection engine.
    Designed to run at 1-2 fps in the background.
    """

    SCAN_INTERVAL = 2.0      # seconds between full scans
    CACHE_TTL     = 10.0     # seconds to hold a threat alert

    def __init__(self):
        self._http = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            headers={"Authorization": f"Bearer {KEY}",
                     "HTTP-Referer": "https://edith-ar.local",
                     "X-Title": "EDITH Privacy"},
            timeout=12.0,
        )
        self._last_scan:   float = 0.0
        self._last_result: dict  = {"level": "green", "threats": []}
        self._threat_cache: dict = {}
        log.info("PrivacySentinel ready")

    async def scan(self, image_b64: str, force: bool = False) -> dict:
        """
        Scan the current camera frame for privacy threats.
        Throttled to SCAN_INTERVAL seconds unless force=True.
        Returns threat assessment dict.
        """
        now = time.time()
        if not force and (now - self._last_scan) < self.SCAN_INTERVAL:
            return self._last_result
        if not image_b64:
            return self._last_result

        self._last_scan = now

        # Step 1: Local pixel analysis (fast, no API)
        local_result = self._local_ir_scan(image_b64)

        # Step 2: Vision model analysis (slower, accurate)
        if KEY:
            ai_result = await self._ai_scan(image_b64)
        else:
            ai_result = {"threats": [], "level": "green"}

        # Merge results — take highest threat level
        threats    = local_result.get("suspects", []) + ai_result.get("threats", [])
        level      = self._compute_level(threats)

        result = {
            "level":      level,
            "threats":    threats,
            "timestamp":  now,
            "speech":     self._build_speech(level, threats),
            "hud_data": {
                "type":    "privacy_overlay",
                "level":   level,
                "threats": threats,
                "colour":  {"green":"#30ff80","amber":"#f0c040","red":"#ff3b30"}[level],
            }
        }
        self._last_result = result
        return result

    def _local_ir_scan(self, image_b64: str) -> dict:
        """
        Fast local analysis — detect bright circular reflections
        (lens IR signature) using numpy pixel statistics.
        No API call needed.
        """
        suspects = []
        try:
            from PIL import Image
            data   = base64.b64decode(image_b64)
            img    = Image.open(io.BytesIO(data)).convert("RGB")
            arr    = np.array(img, dtype=np.float32)
            w, h   = img.size

            # Look for bright circular highlights (IR reflections from lenses)
            # High brightness regions with very high red/green channels
            brightness = arr.mean(axis=2)
            # Threshold: top 0.1% of brightest pixels
            threshold  = np.percentile(brightness, 99.9)
            bright_px  = (brightness > threshold)
            bright_pct = bright_px.sum() / (w * h)

            if bright_pct > 0.0002:  # small but distinct bright spot
                # Find centroid
                ys, xs = np.where(bright_px)
                if len(xs) > 0:
                    cx = int(xs.mean() / w * 100)
                    cy = int(ys.mean() / h * 100)
                    suspects.append({
                        "type":       "ir_reflection",
                        "label":      "Possible lens reflection",
                        "confidence": round(min(0.7, bright_pct * 500), 2),
                        "position":   {"x_pct": cx, "y_pct": cy},
                        "bbox":       {"x": cx-5, "y": cy-5, "w": 10, "h": 10},
                    })

        except Exception as e:
            log.debug(f"Local IR scan error: {e}")

        return {"suspects": suspects}

    async def _ai_scan(self, image_b64: str) -> dict:
        """Vision model scan for smart glasses and recording devices."""
        try:
            r = await self._http.post("/chat/completions", json={
                "model": MODEL,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text", "text": (
                        "Privacy scan: identify any cameras, smart glasses, recording devices, "
                        "surveillance equipment, or active LED indicators in this image. "
                        "Include: Meta Ray-Bans, Snap Spectacles, webcams, CCTV, ring doorbells, "
                        "hidden cameras, phones pointed at viewer, or any recording LEDs. "
                        "Return JSON: {\"threats\":[{\"label\":\"...\",\"confidence\":0.9,"
                        "\"threat_level\":\"red|amber|green\","
                        "\"bbox\":{\"x\":10,\"y\":20,\"w\":30,\"h\":40}}]}"
                        "\nIf nothing suspicious found, return {\"threats\":[]}"
                    )}
                ]}],
                "max_tokens": 300,
            })
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = raw.replace("```json","").replace("```","").strip()
            data = json.loads(raw)
            threats = data.get("threats", [])
            # Validate confidence threshold
            threats = [t for t in threats if t.get("confidence", 0) > 0.5]
            return {"threats": threats, "level": self._compute_level(threats)}
        except Exception as e:
            log.debug(f"AI privacy scan: {e}")
            return {"threats": [], "level": "green"}

    def _compute_level(self, threats: list) -> str:
        if not threats:
            return "green"
        labels = " ".join(t.get("label","").lower() for t in threats)
        types  = " ".join(t.get("type","").lower() for t in threats)
        combined = labels + " " + types
        # Check for red keywords
        if any(k in combined for k in RED_KEYWORDS):
            return "red"
        # Check AI-assigned threat levels
        levels = [t.get("threat_level","green") for t in threats]
        if "red" in levels:
            return "red"
        if "amber" in levels or any(k in combined for k in AMBER_KEYWORDS):
            return "amber"
        return "green"

    def _build_speech(self, level: str, threats: list) -> str:
        if level == "green":
            return "Privacy clear. No recording devices detected."
        elif level == "amber":
            labels = ", ".join(set(t.get("label","device") for t in threats[:2]))
            return f"Privacy alert: possible recording device nearby — {labels}."
        else:
            labels = ", ".join(set(t.get("label","device") for t in threats[:2]))
            return f"WARNING: Recording device detected — {labels}. Exercise caution."

    @property
    def current_level(self) -> str:
        return self._last_result.get("level", "green")

    @property
    def last_result(self) -> dict:
        return self._last_result
