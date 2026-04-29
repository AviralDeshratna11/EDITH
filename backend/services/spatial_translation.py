"""
EDITH Feature: Ambient Spatial Translation
==========================================
Real-time AR subtitle overlay that follows the speaker's position in 3D space.

Pipeline:
  1. ML2 multi-mic array → speaker localization (azimuth/elevation)
  2. Deepgram Nova-3 → streaming STT with language detection
  3. OpenRouter → translation to user's preferred language
  4. ML2 spatial mapper → project subtitles at speaker's world position
     (depth-correct so they don't clip through walls)

Subtitle Display:
  - "Clean Glass" rounded bubble follows speaker's mouth
  - Fades in/out smoothly with speech pauses
  - Colour-coded per speaker (up to 4 simultaneous speakers)
  - Shows original + translation in two lines

Speaker Diarization:
  - Up to 4 simultaneous speakers tracked
  - Each assigned a unique colour (cyan, gold, green, purple)
  - Position updated from face tracking in CV camera

Language Auto-detection:
  - Deepgram detects language automatically
  - Translates to user's preferred language (default: English)
  - Shows both original and translation
"""

import os, json, logging, time, asyncio
from collections import deque
from typing import Optional
import httpx

log = logging.getLogger("EDITH.Translation")

KEY       = os.getenv("OPENROUTER_API_KEY", "")
DG_KEY    = os.getenv("DEEPGRAM_API_KEY", "")
USER_LANG = os.getenv("USER_LANGUAGE", "English")   # Target language

# Speaker colour palette — "Clean Glass" aesthetic
SPEAKER_COLOURS = ["#00f5ff", "#f0c040", "#30ff80", "#c070ff"]

# Language detection via Deepgram (returns BCP-47 codes)
LANG_NAMES = {
    "en":"English","hi":"Hindi","es":"Spanish","fr":"French","de":"German",
    "zh":"Chinese","ja":"Japanese","ar":"Arabic","pt":"Portuguese","ru":"Russian",
    "ko":"Korean","it":"Italian","nl":"Dutch","pl":"Polish","tr":"Turkish",
}


class Speaker:
    def __init__(self, sid: int, position: dict = None):
        self.sid      = sid
        self.colour   = SPEAKER_COLOURS[sid % len(SPEAKER_COLOURS)]
        self.position = position or {"x":0,"y":1.6,"z":-2}
        self.subtitles: deque = deque(maxlen=5)
        self.last_speech = time.time()

    def add_subtitle(self, original: str, translated: str, lang: str):
        self.subtitles.append({
            "original":   original,
            "translated": translated,
            "lang":       lang,
            "ts":         time.time(),
        })
        self.last_speech = time.time()

    @property
    def is_active(self) -> bool:
        return (time.time() - self.last_speech) < 3.0

    @property
    def current_subtitle(self) -> Optional[dict]:
        if self.subtitles:
            return self.subtitles[-1]
        return None


class SpatialTranslationService:
    """
    Real-time multi-speaker translation with 3D subtitle positioning.
    """

    TRANSLATION_CACHE_TTL = 60    # cache identical phrase translations
    MAX_SPEAKERS          = 4

    def __init__(self):
        self._http        = httpx.AsyncClient(timeout=10.0,
            headers={"Authorization": f"Bearer {KEY}",
                     "HTTP-Referer": "https://edith-ar.local"})
        self._speakers:   dict[str, Speaker]  = {}
        self._trans_cache: dict[str,str]       = {}
        self._active      = False
        self._session_id  = 0
        log.info(f"SpatialTranslation ready | target={USER_LANG} DG={'SET' if DG_KEY else 'missing'}")

    def start(self):
        self._active = True
        log.info("Spatial translation: ACTIVE")

    def stop(self):
        self._active = False
        log.info("Spatial translation: STOPPED")

    async def process_utterance(self, audio_b64: str = None,
                                 transcript: str = None,
                                 detected_lang: str = "en",
                                 speaker_id: str = "speaker_0",
                                 speaker_position: dict = None) -> Optional[dict]:
        """
        Process one utterance from a speaker.
        Either audio_b64 (raw PCM) or transcript (pre-transcribed) must be provided.

        Returns subtitle dict for HUD rendering.
        """
        if not self._active:
            return None

        # Get or create speaker
        if speaker_id not in self._speakers:
            idx = len(self._speakers) % self.MAX_SPEAKERS
            self._speakers[speaker_id] = Speaker(idx, speaker_position)
        speaker = self._speakers[speaker_id]
        if speaker_position:
            speaker.position = speaker_position

        # Transcribe if needed
        if transcript is None and audio_b64 and DG_KEY:
            transcript, detected_lang = await self._transcribe(audio_b64)
        if not transcript:
            return None

        # Skip translation if already in user's language
        lang_name = LANG_NAMES.get(detected_lang, detected_lang)
        if lang_name.lower() == USER_LANG.lower():
            translated = transcript
        else:
            translated = await self._translate(transcript, lang_name)

        speaker.add_subtitle(transcript, translated, detected_lang)

        result = {
            "speaker_id":  speaker_id,
            "colour":      speaker.colour,
            "position":    speaker.position,
            "original":    transcript,
            "translated":  translated,
            "lang":        lang_name,
            "is_foreign":  lang_name.lower() != USER_LANG.lower(),
            "hud_data": {
                "type":        "spatial_subtitle",
                "speaker_id":  speaker_id,
                "colour":      speaker.colour,
                "position":    speaker.position,
                "original":    transcript,
                "translated":  translated,
                "lang":        lang_name,
                "show_original": lang_name.lower() != USER_LANG.lower(),
            }
        }
        return result

    async def _transcribe(self, audio_b64: str) -> tuple[str, str]:
        """Deepgram batch transcription with language detection."""
        try:
            import base64
            audio_bytes = base64.b64decode(audio_b64)
            r = await self._http.post(
                "https://api.deepgram.com/v1/listen",
                headers={"Authorization": f"Token {DG_KEY}",
                         "Content-Type": "audio/raw"},
                params={"encoding":"linear16","sample_rate":16000,
                        "channels":1,"model":"nova-3",
                        "detect_language":"true","smart_format":"true",
                        "diarize":"true"},
                content=audio_bytes,
            )
            result   = r.json().get("results",{})
            channel  = result.get("channels",[{}])[0]
            alt      = channel.get("alternatives",[{}])[0]
            text     = alt.get("transcript","")
            lang     = channel.get("detected_language","en")
            return text, lang
        except Exception as e:
            log.error(f"Deepgram transcribe: {e}")
            return "", "en"

    async def _translate(self, text: str, from_lang: str) -> str:
        """Translate text using OpenRouter (fast model for low latency)."""
        cache_key = f"{from_lang}:{text}"
        if cache_key in self._trans_cache:
            return self._trans_cache[cache_key]
        if not KEY:
            return text
        try:
            r = await self._http.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": "meta-llama/llama-3.1-8b-instruct",
                    "messages": [{"role":"user","content":
                        f"Translate from {from_lang} to {USER_LANG}. "
                        f"Return only the translation, no explanation.\n\nText: {text}"}],
                    "max_tokens": 200,
                }
            )
            translated = r.json()["choices"][0]["message"]["content"].strip()
            self._trans_cache[cache_key] = translated
            return translated
        except Exception as e:
            log.error(f"Translation error: {e}")
            return text

    def get_active_subtitles(self) -> list[dict]:
        """Return subtitles for all currently active speakers."""
        result = []
        for sid, speaker in self._speakers.items():
            if speaker.is_active and speaker.current_subtitle:
                sub = speaker.current_subtitle
                result.append({
                    "speaker_id": sid,
                    "colour":     speaker.colour,
                    "position":   speaker.position,
                    "original":   sub["original"],
                    "translated": sub["translated"],
                    "lang":       sub["lang"],
                })
        return result

    def update_speaker_position(self, speaker_id: str, xyz: dict):
        """Update speaker's 3D position from ML2 face tracking."""
        if speaker_id in self._speakers:
            self._speakers[speaker_id].position = xyz

    def clear_speakers(self):
        self._speakers.clear()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def speaker_count(self) -> int:
        return sum(1 for s in self._speakers.values() if s.is_active)
