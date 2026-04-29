"""EDITH Memory Service — episodic memory + gaze state per session"""
import time, logging
from collections import defaultdict, deque

log = logging.getLogger("EDITH.Memory")


class MemoryService:
    MAX_TURNS = 50

    def __init__(self):
        self._sessions:   dict[str, deque] = defaultdict(lambda: deque(maxlen=self.MAX_TURNS))
        self._gaze_state: dict[str, dict]  = {}
        log.info("MemoryService ready")

    def add(self, session_id: str, role: str, content: str, meta: dict = None):
        self._sessions[session_id].append({
            "role": role, "content": content,
            "timestamp": time.time(), "meta": meta or {}
        })

    def get_recent(self, session_id: str, n: int = 6) -> list:
        turns = list(self._sessions[session_id])[-n:]
        return [{"role": t["role"], "content": t["content"]} for t in turns]

    def clear(self, session_id: str):
        self._sessions.pop(session_id, None)
        self._gaze_state.pop(session_id, None)

    async def update_gaze(self, session_id: str, target: str, duration_ms: int) -> bool:
        prev   = self._gaze_state.get(session_id, {})
        is_new = prev.get("target") != target
        self._gaze_state[session_id] = {
            "target": target, "is_new": is_new,
            "since": time.time() if is_new else prev.get("since", time.time()),
            "duration_ms": duration_ms,
        }
        return is_new

    def get_gaze(self, session_id: str) -> dict:
        return self._gaze_state.get(session_id, {})
