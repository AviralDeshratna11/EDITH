"""
EDITH Feature 3 — Remote Photoplethysmography (rPPG) Biometric Sensing
=======================================================================
Estimates heart rate + stress level from skin colour fluctuations
in the ML2 CV camera stream — no contact, no wearable required.

Algorithm (CHROM method — most robust for colour cameras):
  1. Receive 10-second buffer of face-crop frames (base64 JPEG)
  2. Extract mean RGB per frame → G channel dominates pulse signal
  3. Detrend with polynomial fit → remove slow illumination drift
  4. Apply Butterworth band-pass filter (0.75–3.0 Hz = 45–180 bpm)
  5. FFT → dominant frequency = heart rate
  6. Amplitude variance → stress proxy (high HRV = calm, low = stressed)

Winning HUD Display:
  - Real-time BPM gauge (green=normal / amber=elevated / red=high)
  - HRV-based stress indicator (0–100%)
  - 10-second pulse waveform chart
"""

import os, base64, logging, io, time
from collections import deque
from typing import Optional

import numpy as np
from scipy.signal import butter, filtfilt, detrend

log = logging.getLogger("EDITH.rPPG")

# Normal adult HR range for colour mapping
BPM_LOW    = 60
BPM_HIGH   = 100
BPM_MAX    = 180
FPS_TARGET = 10          # frames per second from ML2 CV camera
WINDOW_S   = 10          # seconds of frames needed for reliable estimate
MIN_FRAMES = FPS_TARGET * WINDOW_S


def _butter_bandpass(lowcut: float, highcut: float, fs: float, order: int = 4):
    nyq  = fs / 2.0
    low  = lowcut  / nyq
    high = highcut / nyq
    b, a = butter(order, [low, high], btype="band")
    return b, a


def _bandpass_filter(signal: np.ndarray, lowcut: float, highcut: float,
                     fs: float) -> np.ndarray:
    b, a = _butter_bandpass(lowcut, highcut, fs)
    return filtfilt(b, a, signal)


class RPPGSensor:
    """
    Per-session rPPG estimator.
    Feed JPEG face-crop frames at ~10fps; call estimate() for results.
    """

    def __init__(self, fps: float = FPS_TARGET):
        self._fps      = fps
        self._r_buf:   deque = deque(maxlen=MIN_FRAMES * 2)
        self._g_buf:   deque = deque(maxlen=MIN_FRAMES * 2)
        self._b_buf:   deque = deque(maxlen=MIN_FRAMES * 2)
        self._times:   deque = deque(maxlen=MIN_FRAMES * 2)
        self._last_est: dict = {}
        log.info(f"rPPG sensor ready | fps={fps} window={WINDOW_S}s")

    def push_frame(self, jpeg_b64: str) -> bool:
        """
        Decode JPEG, extract mean RGB from central face region, push to buffers.
        Returns True if enough frames for an estimate.
        """
        try:
            data  = base64.b64decode(jpeg_b64)
            # Decode with PIL (lighter than cv2)
            from PIL import Image
            img   = Image.open(io.BytesIO(data)).convert("RGB")
            w, h  = img.size
            # Central 40% crop (likely to contain forehead/cheeks)
            cx, cy = w//2, h//2
            pad    = min(w, h) // 5
            roi    = img.crop((cx-pad, cy-pad*2, cx+pad, cy+pad))
            arr    = np.array(roi, dtype=np.float32)
            self._r_buf.append(arr[:,:,0].mean())
            self._g_buf.append(arr[:,:,1].mean())
            self._b_buf.append(arr[:,:,2].mean())
            self._times.append(time.time())
            return len(self._g_buf) >= MIN_FRAMES
        except Exception as e:
            log.debug(f"rPPG frame error: {e}")
            return False

    def estimate(self) -> Optional[dict]:
        """
        Run rPPG analysis on buffered frames.
        Returns {bpm, stress_pct, hrv_ms, confidence, waveform, colour}.
        """
        if len(self._g_buf) < MIN_FRAMES:
            frames_needed = MIN_FRAMES - len(self._g_buf)
            return {"status": "collecting",
                    "frames_needed": frames_needed,
                    "progress_pct": round(len(self._g_buf)/MIN_FRAMES*100)}

        try:
            return self._run_chrom()
        except Exception as e:
            log.error(f"rPPG estimation error: {e}")
            return {"status": "error", "message": str(e)}

    def _run_chrom(self) -> dict:
        """CHROM rPPG algorithm."""
        r = np.array(self._r_buf, dtype=np.float64)
        g = np.array(self._g_buf, dtype=np.float64)
        b = np.array(self._b_buf, dtype=np.float64)

        # Normalise channels
        r_n = r / (r.mean() + 1e-6)
        g_n = g / (g.mean() + 1e-6)
        b_n = b / (b.mean() + 1e-6)

        # CHROM: X = 3R - 2G,  Y = 1.5R + G - 1.5B
        X = 3*r_n - 2*g_n
        Y = 1.5*r_n + g_n - 1.5*b_n
        alpha = X.std() / (Y.std() + 1e-6)
        pulse_signal = X - alpha * Y

        # Detrend (remove slow drift)
        pulse_signal = detrend(pulse_signal)

        # Estimate actual fps from timestamps
        ts   = np.array(self._times)
        fps  = len(ts) / (ts[-1] - ts[0] + 1e-6)

        # Band-pass filter: 45–180 bpm = 0.75–3.0 Hz
        filtered = _bandpass_filter(pulse_signal, 0.75, 3.0, fps)

        # FFT → dominant frequency
        n     = len(filtered)
        freqs = np.fft.rfftfreq(n, d=1.0/fps)
        power = np.abs(np.fft.rfft(filtered)) ** 2
        # Only look in 0.75–3.0 Hz range
        mask  = (freqs >= 0.75) & (freqs <= 3.0)
        if not mask.any():
            return {"status": "error", "message": "No valid frequency band"}
        peak_freq = freqs[mask][power[mask].argmax()]
        bpm       = round(peak_freq * 60, 1)

        # HRV proxy: standard deviation of inter-beat intervals
        # Simplified: std of filtered signal amplitude changes
        hrv_ms = round(float(np.std(np.diff(filtered)) * 1000), 1)

        # Stress score: low HRV → high stress
        # Normal HRV ~ 20-100ms; below 20 = stressed
        stress_pct = max(0, min(100, round(100 - min(hrv_ms, 80) / 80 * 100)))

        # Confidence: based on SNR
        snr = power[mask].max() / (power[mask].mean() + 1e-6)
        confidence = min(1.0, round(float(snr) / 20, 2))

        # Waveform: last 3 seconds normalised for HUD display
        n_wave = int(fps * 3)
        wave   = filtered[-n_wave:].tolist()
        wmax   = max(abs(min(wave)), abs(max(wave))) + 1e-6
        wave   = [round(v / wmax, 3) for v in wave]

        # Colour coding
        if bpm < BPM_LOW:    colour = "#60a0ff"   # bradycardia (blue)
        elif bpm <= BPM_HIGH: colour = "#30ff80"  # normal (green)
        elif bpm <= 120:      colour = "#f0c040"  # elevated (amber)
        else:                 colour = "#ff3b30"  # tachycardia (red)

        self._last_est = {
            "status":      "ready",
            "bpm":         bpm,
            "stress_pct":  stress_pct,
            "hrv_ms":      hrv_ms,
            "confidence":  confidence,
            "waveform":    wave,
            "colour":      colour,
            "fps_actual":  round(fps, 1),
            "frames_used": n,
        }
        return self._last_est

    @property
    def last(self) -> dict:
        return self._last_est

    def reset(self):
        self._r_buf.clear(); self._g_buf.clear()
        self._b_buf.clear(); self._times.clear()


class RPPGService:
    """Multi-session rPPG manager."""

    def __init__(self):
        self._sessions: dict[str, RPPGSensor] = {}
        log.info("RPPGService ready")

    def push_frame(self, session_id: str, jpeg_b64: str) -> bool:
        if session_id not in self._sessions:
            self._sessions[session_id] = RPPGSensor()
        return self._sessions[session_id].push_frame(jpeg_b64)

    def estimate(self, session_id: str) -> dict:
        if session_id not in self._sessions:
            return {"status": "no_session"}
        return self._sessions[session_id].estimate()

    def reset(self, session_id: str):
        self._sessions.pop(session_id, None)
