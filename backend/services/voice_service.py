"""
EDITH Voice Service
===================
STT: Groq Whisper (primary, free) → Deepgram Nova-3 → no-key fallback
TTS: ElevenLabs (primary, JARVIS voice) → Cartesia → gTTS (always works)
"""
import os, asyncio, base64, json, logging, io, struct
from typing import AsyncGenerator
import httpx

log = logging.getLogger("EDITH.Voice")

ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VID = os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
CARTESIA_KEY   = os.getenv("CARTESIA_API_KEY", "")
CARTESIA_VID   = os.getenv("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091")
GROQ_KEY       = os.getenv("GROQ_API_KEY", "")
DG_KEY         = os.getenv("DEEPGRAM_API_KEY", "")


def _tts() -> str:
    if ELEVENLABS_KEY: return "elevenlabs"
    if CARTESIA_KEY:   return "cartesia"
    return "gtts"

def _stt() -> str:
    if GROQ_KEY: return "groq"
    if DG_KEY:   return "deepgram"
    return "none"


class VoiceService:
    def __init__(self):
        self._http = httpx.AsyncClient(timeout=25.0)
        self._bufs: dict[str, list[bytes]] = {}
        self._dg:   dict[str, "_DGSession"] = {}
        log.info(f"VoiceService | TTS={_tts()} | STT={_stt()}")
        if _tts() == "gtts" and _stt() == "none":
            log.warning("No voice API keys. Add GROQ_API_KEY + ELEVENLABS_API_KEY to .env")

    # ── STT ──────────────────────────────────────────────────────────────

    async def process_chunk(self, audio_b64: str, session_id: str,
                             is_final: bool) -> str | None:
        """
        Accepts base64-encoded PCM-16 chunks from streaming WebSocket.
        Returns transcript string when utterance ends, None otherwise.
        NOTE: Android app uses /api/transcribe (WAV upload) instead — this
        path is only for browser-based streaming (Deepgram WS).
        """
        if not audio_b64:
            # Empty chunk = stop signal. Never return __no_stt__ here —
            # that would cause a false error toast on ML2 Android path.
            return None

        mode = _stt()

        if mode == "deepgram":
            if session_id not in self._dg:
                s = _DGSession(DG_KEY); await s.connect()
                self._dg[session_id] = s
            return await self._dg[session_id].push(base64.b64decode(audio_b64), is_final)

        # Groq / no-key: accumulate
        if session_id not in self._bufs:
            self._bufs[session_id] = []
        self._bufs[session_id].append(base64.b64decode(audio_b64))

        if is_final:
            raw = b"".join(self._bufs.pop(session_id, []))
            if mode == "groq" and raw:
                return await self._groq_bytes(raw, "audio.wav")
            # No STT key and real audio came in — tell user to type
            # (only fires for browser path, not Android which uses /api/transcribe)
            if raw:
                return "__no_stt__"

        return None

    async def transcribe_wav(self, audio_b64: str) -> str:
        """Called from /api/transcribe — full WAV from Android VoiceService."""
        try:
            data = base64.b64decode(audio_b64)
        except Exception:
            return ""
        mode = _stt()
        if mode == "groq":      return await self._groq_bytes(data, "audio.wav")
        if mode == "deepgram":  return await self._dg_batch(data)
        return ""

    async def _groq_bytes(self, data: bytes, filename: str) -> str:
        # If raw PCM (no WAV header), wrap it
        if not data[:4] == b"RIFF":
            data = _pcm_to_wav(data)
        try:
            r = await self._http.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_KEY}"},
                files={"file": (filename, data, "audio/wav")},
                data={"model": "whisper-large-v3-turbo", "response_format": "json", "language": "en"},
                timeout=20.0,
            )
            if r.status_code == 200:
                text = r.json().get("text","").strip()
                log.info(f"Groq transcript: '{text}'")
                return text
            log.error(f"Groq {r.status_code}: {r.text[:200]}")
            return ""
        except Exception as e:
            log.error(f"Groq: {e}"); return ""

    async def _dg_batch(self, data: bytes) -> str:
        try:
            ct = "audio/wav" if data[:4]==b"RIFF" else "audio/raw"
            params = {"model":"nova-3","smart_format":"true"}
            if ct == "audio/raw":
                params.update({"encoding":"linear16","sample_rate":"16000","channels":"1"})
            r = await self._http.post(
                "https://api.deepgram.com/v1/listen",
                headers={"Authorization":f"Token {DG_KEY}","Content-Type":ct},
                params=params, content=data, timeout=20.0,
            )
            if r.status_code == 200:
                return (r.json().get("results",{}).get("channels",[{}])[0]
                               .get("alternatives",[{}])[0].get("transcript","").strip())
            return ""
        except Exception as e:
            log.error(f"Deepgram batch: {e}"); return ""

    async def cleanup_session(self, sid: str):
        self._bufs.pop(sid, None)
        if sid in self._dg:
            await self._dg.pop(sid).close()

    # ── TTS ──────────────────────────────────────────────────────────────

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        if not text.strip():
            return
        mode = _tts()
        log.info(f"TTS[{mode}]: '{text[:50]}'")
        if mode == "elevenlabs":
            async for c in self._el_stream(text): yield c
        elif mode == "cartesia":
            async for c in self._cartesia(text): yield c
        else:
            async for c in self._gtts(text): yield c

    async def _el_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """ElevenLabs streaming MP3 — George voice (deep, JARVIS-like)."""
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VID}/stream"
            async with self._http.stream(
                "POST", url,
                json={
                    "text":           text,
                    "model_id":       "eleven_turbo_v2_5",
                    "voice_settings": {
                        "stability":        0.45,
                        "similarity_boost": 0.80,
                        "style":            0.20,
                        "use_speaker_boost": True,
                    },
                    "output_format": "mp3_44100_128",
                },
                headers={"xi-api-key": ELEVENLABS_KEY, "Accept": "audio/mpeg"},
                timeout=30.0,
            ) as r:
                if r.status_code != 200:
                    body = await r.aread()
                    log.error(f"ElevenLabs {r.status_code}: {body[:200]}")
                    async for c in self._gtts(text): yield c
                    return
                async for chunk in r.aiter_bytes(4096):
                    if chunk:
                        yield base64.b64encode(chunk).decode()
        except Exception as e:
            log.error(f"ElevenLabs: {e}")
            async for c in self._gtts(text): yield c

    async def _cartesia(self, text: str) -> AsyncGenerator[bytes, None]:
        try:
            async with self._http.stream(
                "POST", "https://api.cartesia.ai/tts/bytes",
                json={"model_id":"sonic-2024-10-19","transcript":text,
                      "voice":{"mode":"id","id":CARTESIA_VID},
                      "output_format":{"container":"raw","encoding":"pcm_s16le","sample_rate":22050},
                      "stream":True},
                headers={"X-API-Key":CARTESIA_KEY,"Cartesia-Version":"2024-06-10"},
                timeout=20.0,
            ) as r:
                async for chunk in r.aiter_bytes(4096):
                    if chunk: yield base64.b64encode(chunk).decode()
        except Exception as e:
            log.error(f"Cartesia: {e}")
            async for c in self._gtts(text): yield c

    async def _gtts(self, text: str) -> AsyncGenerator[bytes, None]:
        try:
            from gtts import gTTS
            tts = gTTS(text=text, lang="en", slow=False)
            buf = io.BytesIO(); tts.write_to_fp(buf); buf.seek(0)
            data = buf.read()
            for i in range(0, len(data), 8192):
                yield base64.b64encode(data[i:i+8192]).decode()
        except Exception as e:
            log.error(f"gTTS: {e}")

    async def synthesize_full(self, text: str) -> bytes:
        chunks = [base64.b64decode(c) async for c in self.synthesize_stream(text)]
        return b"".join(chunks)

    @property
    def tts_mode(self) -> str: return _tts()
    @property
    def stt_mode(self) -> str: return _stt()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pcm_to_wav(pcm: bytes, sr: int = 16000) -> bytes:
    ch, bits = 1, 16
    buf = io.BytesIO()
    buf.write(b"RIFF"); buf.write(struct.pack("<I", 36+len(pcm)))
    buf.write(b"WAVEfmt "); buf.write(struct.pack("<IHHIIHH",16,1,ch,sr,sr*ch*bits//8,ch*bits//8,bits))
    buf.write(b"data"); buf.write(struct.pack("<I", len(pcm))); buf.write(pcm)
    return buf.getvalue()


class _DGSession:
    URL = ("wss://api.deepgram.com/v1/listen"
           "?model=nova-3&encoding=linear16&sample_rate=16000"
           "&channels=1&interim_results=true&smart_format=true&endpointing=300")
    def __init__(self, key): self._key=key; self._ws=None; self._buf=""; self._task=None
    async def connect(self):
        try:
            import websockets
            self._ws=await websockets.connect(self.URL,extra_headers={"Authorization":f"Token {self._key}"})
            self._task=asyncio.create_task(self._recv())
        except Exception as e: log.error(f"DG WS: {e}")
    async def push(self, pcm, is_final):
        if not self._ws: return None
        try:
            await self._ws.send(pcm)
            if is_final:
                await self._ws.send(json.dumps({"type":"CloseStream"}))
                await asyncio.sleep(0.4)
                r=self._buf.strip(); self._buf=""; return r or None
        except Exception as e: log.error(f"DG push: {e}")
        return None
    async def _recv(self):
        try:
            async for msg in self._ws:
                d=json.loads(msg)
                if d.get("type")=="Results" and d.get("is_final"):
                    a=d.get("channel",{}).get("alternatives",[{}])[0].get("transcript","")
                    if a: self._buf+=" "+a
        except Exception: pass
    async def close(self):
        if self._ws: await self._ws.close()
        if self._task: self._task.cancel()
