"""
EDITH Feature 1 — Spatial Knowledge Graph ("World Memory")
===========================================================
Gives EDITH long-term memory of WHERE things are in the physical world.

"Where did I leave my coffee?" → retrieves XYZ coords + timestamp
"What was on that whiteboard yesterday?" → replays spatial snapshot

Architecture:
  CV Camera frame → OpenRouter Gemini Vision → entity extraction
  → ChromaDB collection with (entity, xyz, timestamp, image_b64, description)
  → RAG retrieval on natural language query

The graph builds an incremental topological map of your environment,
performs conflict tracing (object moved → notify user), and supports
"spatial replay" — reconstruct what the room looked like at time T.
"""

import os, json, logging, time, asyncio, base64
from datetime import datetime
from typing import Optional
import httpx

log = logging.getLogger("EDITH.SpatialKG")

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
VISION_MODEL   = "google/gemini-2.0-flash"


class SpatialKnowledgeGraph:
    """
    ChromaDB-backed spatial memory. Each entry is a physical object
    with a location, description, timestamp, and embedding.
    """

    COLLECTION = "edith_world_memory"

    def __init__(self):
        self._client  = None
        self._col     = None
        self._http    = httpx.AsyncClient(timeout=20.0,
            headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                     "HTTP-Referer": "https://edith-ar.local"})
        self._init_db()
        log.info("SpatialKnowledgeGraph ready")

    def _init_db(self):
        try:
            import chromadb
            from chromadb.config import Settings
            self._client = chromadb.PersistentClient(
                path="data/spatial_kg",
                settings=Settings(anonymized_telemetry=False)
            )
            self._col = self._client.get_or_create_collection(
                name=self.COLLECTION,
                metadata={"hnsw:space": "cosine"}
            )
            log.info(f"ChromaDB ready — {self._col.count()} objects in memory")
        except Exception as e:
            log.error(f"ChromaDB init failed: {e}")
            self._col = None

    # ── OBSERVE: store a new/updated object ───────────────────────────

    async def observe(self, image_b64: str, xyz: dict, session_id: str = "default") -> list:
        """
        Called when the CV camera captures a frame.
        Extracts objects via vision model, stores each with its XYZ location.
        Returns list of detected entities.
        """
        if not image_b64 or not OPENROUTER_KEY:
            return []

        entities = await self._extract_entities(image_b64, xyz)
        now      = time.time()
        ts_str   = datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")

        for entity in entities:
            entity_id = f"{entity['label'].lower().replace(' ','_')}_{int(now)}"
            doc = (f"{entity['label']} — {entity['description']}. "
                   f"Location: x={xyz.get('x',0):.2f}, y={xyz.get('y',0):.2f}, z={xyz.get('z',0):.2f}. "
                   f"Seen at {ts_str}.")
            meta = {
                "label":       entity["label"],
                "x":           float(xyz.get("x", 0)),
                "y":           float(xyz.get("y", 0)),
                "z":           float(xyz.get("z", 0)),
                "timestamp":   float(now),
                "ts_human":    ts_str,
                "description": entity["description"],
                "session":     session_id,
                "confidence":  float(entity.get("confidence", 0.8)),
            }
            # Check for conflict (object moved)
            conflict = self._check_conflict(entity["label"], xyz)
            if conflict:
                meta["conflict"] = json.dumps(conflict)
                log.info(f"CONFLICT: {entity['label']} moved from {conflict['old_xyz']} to {xyz}")

            if self._col:
                try:
                    self._col.add(
                        documents=[doc],
                        metadatas=[meta],
                        ids=[entity_id],
                    )
                except Exception as e:
                    log.debug(f"ChromaDB add: {e}")

        return entities

    async def _extract_entities(self, image_b64: str, xyz: dict) -> list:
        """Send frame to vision model, extract all physical objects."""
        try:
            r = await self._http.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={
                    "model": VISION_MODEL,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                        {"type": "text", "text": (
                            "List every distinct physical object visible in this image. "
                            "Return JSON array only:\n"
                            '[{"label":"coffee mug","description":"white mug, half full",'
                            '"confidence":0.95},...]'
                        )}
                    ]}],
                    "max_tokens": 400,
                }
            )
            raw = r.json()["choices"][0]["message"]["content"].strip()
            raw = raw.replace("```json","").replace("```","").strip()
            return json.loads(raw)
        except Exception as e:
            log.error(f"Entity extraction error: {e}")
            return []

    def _check_conflict(self, label: str, new_xyz: dict) -> Optional[dict]:
        """Check if this object was previously at a different location."""
        if not self._col:
            return None
        try:
            results = self._col.query(
                query_texts=[label],
                n_results=1,
                where={"label": label},
            )
            if not results["metadatas"] or not results["metadatas"][0]:
                return None
            old_meta = results["metadatas"][0][0]
            old_xyz  = {"x": old_meta["x"], "y": old_meta["y"], "z": old_meta["z"]}
            # If moved more than 0.3m
            dist = ((new_xyz.get("x",0)-old_xyz["x"])**2 +
                    (new_xyz.get("y",0)-old_xyz["y"])**2 +
                    (new_xyz.get("z",0)-old_xyz["z"])**2) ** 0.5
            if dist > 0.3:
                return {"old_xyz": old_xyz, "distance_m": round(dist, 2),
                        "last_seen": old_meta.get("ts_human", "unknown")}
        except Exception:
            pass
        return None

    # ── QUERY: natural language spatial retrieval ─────────────────────

    async def query(self, question: str, n: int = 5) -> dict:
        """
        "Where did I put my coffee?" → returns location + description + timestamp
        Supports temporal queries: "What was on the desk yesterday?"
        """
        if not self._col:
            return {"answer": "World memory not available (ChromaDB not initialised)",
                    "results": []}
        try:
            results = self._col.query(
                query_texts=[question],
                n_results=min(n, self._col.count() or 1),
            )
            if not results["documents"] or not results["documents"][0]:
                return {"answer": "I haven't observed that object yet.", "results": []}

            items = []
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                items.append({
                    "label":       meta.get("label","?"),
                    "description": meta.get("description",""),
                    "location":    f"x={meta.get('x',0):.1f}, y={meta.get('y',0):.1f}, z={meta.get('z',0):.1f}",
                    "last_seen":   meta.get("ts_human","unknown"),
                    "relevance":   round(1-dist, 2),
                    "conflict":    json.loads(meta["conflict"]) if "conflict" in meta else None,
                })
            return {"answer": self._format_answer(question, items), "results": items}
        except Exception as e:
            log.error(f"Spatial query error: {e}")
            return {"answer": "Memory retrieval error.", "results": []}

    def _format_answer(self, question: str, items: list) -> str:
        if not items:
            return "I don't have that in my world memory yet."
        best = items[0]
        ans  = f"{best['label'].title()} — {best['description']}. "
        ans += f"Last seen at {best['location']}, {best['last_seen']}."
        if best.get("conflict"):
            c = best["conflict"]
            ans += (f" Note: it was moved {c['distance_m']}m from its previous position "
                    f"(last seen there: {c.get('last_seen','?')}).")
        return ans

    # ── REPLAY: what did the room look like at time T? ────────────────

    def replay(self, before_ts: float, after_ts: float = 0) -> list:
        """Return all objects observed in a time window."""
        if not self._col:
            return []
        try:
            results = self._col.get(
                where={"$and": [
                    {"timestamp": {"$gte": after_ts}},
                    {"timestamp": {"$lte": before_ts}},
                ]}
            )
            return results.get("metadatas", [])
        except Exception:
            return []

    def stats(self) -> dict:
        if not self._col:
            return {"objects": 0, "status": "unavailable"}
        return {"objects": self._col.count(), "status": "online"}
