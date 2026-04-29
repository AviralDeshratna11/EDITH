"""
╔══════════════════════════════════════════════════════════════╗
║         E.D.I.T.H  —  FastAPI Backend  v2.1.0              ║
║   Even Dead, I'm The Hero  |  XRCC 2026                    ║
╚══════════════════════════════════════════════════════════════╝

Run:
    cd backend
    python server.py

Or with auto-reload:
    uvicorn server:app --host 0.0.0.0 --port 8000 --reload
"""

import os, json, asyncio, logging, time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

# Load .env before importing services
from dotenv import load_dotenv
load_dotenv()

from services.llm_service          import LLMService
from services.voice_service        import VoiceService
from services.gmail_service        import GmailService
from services.youtube_service      import YouTubeService
from services.search_service       import SearchService
from services.vision_service       import VisionService
from services.memory_service       import MemoryService
# ── Advanced features ──────────────────────────────────────────
from services.spatial_kg           import SpatialKnowledgeGraph
from services.proactive_engine     import ProactiveEngine
from services.rppg_service         import RPPGService
from services.swarm_orchestrator   import SwarmOrchestrator
from services.ambient_intelligence import AmbientIntelligence
from services.predictive_engine    import PredictiveContextEngine
# ── v3 advanced features ───────────────────────────────────────
from services.aoi_service          import AOIService
from services.whatsapp_service     import WhatsAppService
from services.privacy_sentinel     import PrivacySentinel
from services.affective_ui         import AffectiveUIService
from services.spatial_translation  import SpatialTranslationService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
)
log = logging.getLogger("EDITH")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


# ─────────────────────────────────────────────────────────────────────────────
# LIFESPAN — boot / shutdown
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("⚡ EDITH booting…")
    Path("data").mkdir(exist_ok=True)
    Path("data/spatial_kg").mkdir(exist_ok=True)

    # ── Core services ───────────────────────────────────────────
    app.state.llm     = LLMService()
    app.state.voice   = VoiceService()
    app.state.gmail   = GmailService()
    app.state.youtube = YouTubeService()
    app.state.search  = SearchService()
    app.state.vision  = VisionService()
    app.state.memory  = MemoryService()
    app.state.clients: dict[str, WebSocket] = {}

    # ── Advanced feature services ───────────────────────────────
    app.state.spatial    = SpatialKnowledgeGraph()
    app.state.proactive  = ProactiveEngine()
    app.state.rppg       = RPPGService()
    app.state.ambient    = AmbientIntelligence()
    app.state.predict    = PredictiveContextEngine()
    # Swarm needs references to other services
    app.state.swarm      = SwarmOrchestrator(
        gmail_svc  = app.state.gmail,
        search_svc = app.state.search,
        spatial_kg = app.state.spatial,
    )

    # ── v3 services ─────────────────────────────────────────────
    app.state.aoi         = AOIService()
    app.state.whatsapp    = WhatsAppService()
    app.state.privacy     = PrivacySentinel()
    app.state.affective   = AffectiveUIService()
    app.state.translation = SpatialTranslationService()

    log.info("✅ All services online (core + v2 + v3). EDITH ready.")
    yield
    log.info("🔴 EDITH shutdown.")


app = FastAPI(title="EDITH AR", version="2.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
if FRONTEND_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


@app.get("/setup")
async def setup_page():
    """Setup/diagnostic page — open this first on ML2 browser."""
    setup_file = FRONTEND_DIR / "setup.html"
    if setup_file.exists():
        return FileResponse(str(setup_file))
    return HTMLResponse("<h1>EDITH Setup</h1><p>Run from project root.</p>")


# ─────────────────────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────────────────────

class CommandRequest(BaseModel):
    text:           str
    session_id:     str = "default"
    gaze_target:    Optional[str]   = None
    gaze_duration:  Optional[int]   = 0
    hand_gesture:   Optional[str]   = None
    pupil_dilation: Optional[float] = None
    spatial_anchor: Optional[dict]  = None
    image_b64:      Optional[str]   = None   # camera crop for vision

class ConfirmRequest(BaseModel):
    action:     str
    data:       dict = {}
    session_id: str  = "default"

HUD_MODES = {
    "web_search": "search", "play_youtube": "media", "read_email": "email",
    "send_email": "compose", "summarize_email": "email", "identify_object": "scan",
    "weather": "info", "navigate": "navigation", "system_status": "system",
    "anchor_content": "anchor", "set_reminder": "reminder", "translate": "translate",
    "general_chat": "default",
    # Advanced features
    "swarm_briefing":  "swarm",
    "spatial_query":   "spatial",
    "meeting_summary": "ambient",
    "biometrics":      "biometrics",
    "predict":         "predict",
    # v3 features
    "aoi_scan":        "aoi",
    "whatsapp":        "messaging",
    "privacy_scan":    "privacy",
    "translate_live":  "translation",
}



# ─────────────────────────────────────────────────────────────────────────────
# WEBSOCKET — ML2 real-time stream
# ─────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def ws_endpoint(ws: WebSocket, session_id: str):
    await ws.accept()
    app.state.clients[session_id] = ws
    log.info(f"WS connected: {session_id}")
    try:
        async for raw in ws.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await _handle_ws_message(ws, session_id, msg)
    except WebSocketDisconnect:
        app.state.clients.pop(session_id, None)
        await app.state.voice.cleanup_session(session_id)
        log.info(f"WS disconnected: {session_id}")


async def _handle_ws_message(ws: WebSocket, sid: str, msg: dict):
    t = msg.get("type")

    if t == "audio_chunk":
        transcript = await app.state.voice.process_chunk(
            msg.get("data", ""), sid, msg.get("is_final", False)
        )
        if transcript and transcript.strip():
            await ws.send_json({"type": "transcript", "text": transcript})
            if msg.get("is_final", False):
                req = CommandRequest(
                    text=transcript, session_id=sid,
                    gaze_target=msg.get("gaze_target"),
                    hand_gesture=msg.get("gesture"),
                )
                await _execute_command(req, ws)

    elif t == "text_command":
        req = CommandRequest(
            text=msg.get("text", ""), session_id=sid,
            gaze_target=msg.get("gaze_target"),
            image_b64=msg.get("image_b64"),
        )
        await _execute_command(req, ws)

    elif t == "gaze_update":
        is_new = await app.state.memory.update_gaze(
            sid, msg.get("target", ""), msg.get("duration_ms", 0)
        )
        if is_new and msg.get("duration_ms", 0) > 1500:
            await ws.send_json({
                "type": "proactive_suggestion",
                "text": f"You seem focused on {msg.get('target','this')}. Want me to look into it?",
                "action": "identify_object",
            })

    elif t == "gesture":
        await ws.send_json({"type": "gesture_ack", "gesture": msg.get("gesture")})

    elif t == "ping":
        await ws.send_json({"type": "pong"})

    # ── AOI: long gaze triggers object intelligence scan ────────────────
    elif t == "aoi_scan":
        result = await app.state.aoi.scan(
            image_b64   = msg.get("data",""),
            gaze_hint   = msg.get("gaze_target","object"),
            session_id  = sid,
        )
        await ws.send_json({"type": "aoi_result", **result})

    # ── Privacy: scan frame for cameras/smart glasses ───────────────────
    elif t == "privacy_frame":
        result = await app.state.privacy.scan(msg.get("data",""))
        if result["level"] != "green":
            await ws.send_json({"type": "privacy_alert", **result})

    # ── WhatsApp: new incoming message pushed from webhook ───────────────
    elif t == "whatsapp_check":
        msgs = app.state.whatsapp.get_unread()
        await ws.send_json({
            "type":       "whatsapp_messages",
            "messages":   msgs,
            "unread":     app.state.whatsapp.unread_count,
            "hud_data":   {"type":"whatsapp_bubbles","messages":msgs},
        })

    # ── Translation: utterance from ambient mic ──────────────────────────
    elif t == "translate_utterance":
        result = await app.state.translation.process_utterance(
            transcript        = msg.get("text"),
            audio_b64         = msg.get("audio_b64"),
            detected_lang     = msg.get("lang","en"),
            speaker_id        = msg.get("speaker_id","speaker_0"),
            speaker_position  = msg.get("position"),
        )
        if result:
            await ws.send_json({"type": "subtitle_update", **result})

    # ── rPPG: face frame for biometric sensing ─────────────────────────
    elif t == "rppg_frame":
        ready = app.state.rppg.push_frame(sid, msg.get("data",""))
        if ready:
            result = app.state.rppg.estimate(sid)
            await ws.send_json({"type": "biometrics_update", "data": result})

    # ── Spatial KG: camera frame for world memory ──────────────────────
    elif t == "spatial_frame":
        xyz      = msg.get("xyz", {"x":0,"y":0,"z":0})
        entities = await app.state.spatial.observe(msg.get("data",""), xyz, sid)
        if entities:
            await ws.send_json({"type": "spatial_observed", "entities": entities})

    # ── Ambient audio: push transcribed utterance ──────────────────────
    elif t == "ambient_utterance":
        alerts = app.state.ambient.push_utterance(msg.get("text",""), msg.get("speaker","?"))
        summary = await app.state.ambient.get_summary()
        if alerts.get("alerts") or summary:
            await ws.send_json({
                "type": "ambient_update",
                "alerts": alerts.get("alerts",[]),
                "summary": summary,
            })

    # ── Gaze: now also feeds cognitive load monitor ────────────────────
    elif t == "gaze_update":
        is_new = await app.state.memory.update_gaze(
            sid, msg.get("target",""), msg.get("duration_ms",0)
        )
        # Feed proactive engine
        load = app.state.proactive.push_gaze(
            fixation_ms = msg.get("duration_ms", 0),
            pupil       = msg.get("pupil_dilation", 0.4),
            is_blink    = msg.get("is_blink", False),
            target      = msg.get("target",""),
        )
        # ── Affective UI: pupil dilation stress index ────────────
        pupil_l = msg.get("pupil_left", msg.get("pupil_dilation", 0.4) * 8)
        pupil_r = msg.get("pupil_right", pupil_l)
        affective_state = app.state.affective.push(
            sid, pupil_l, pupil_r,
            is_blink    = msg.get("is_blink", False),
            fixation_ms = msg.get("duration_ms", 0),
        )
        # Push HUD config changes only when state changes
        if affective_state.get("message"):
            await ws.send_json({
                "type":      "affective_update",
                "state":     affective_state,
                "hud_config":affective_state.get("hud_config",{}),
            })
        # Check if proactive intervention needed (every ~20 gaze events)
        if int(time.time()) % 20 == 0:
            scene = msg.get("scene_context","")
            img   = msg.get("image_b64")
            intervention = await app.state.proactive.evaluate(
                gaze_target=msg.get("target",""), scene_context=scene, image_b64=img
            )
            if intervention:
                await ws.send_json({"type": "proactive_intervention", **intervention})

        # Check predictive engine
        if int(time.time()) % 30 == 0:
            prediction = await app.state.predict.predict_next(
                current_location = msg.get("target",""),
                bpm = app.state.rppg.estimate(sid).get("bpm") if sid in app.state.rppg._sessions else None,
            )
            if prediction:
                await ws.send_json({"type": "prediction", **prediction})

        # Original proactive suggestion for new target
        if is_new and msg.get("duration_ms",0) > 1500:
            await ws.send_json({
                "type": "proactive_suggestion",
                "text": f"You seem focused on {msg.get('target','this')}. Want me to look into it?",
                "action": "identify_object",
            })


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND EXECUTOR (shared by WS and REST)
# ─────────────────────────────────────────────────────────────────────────────

async def _execute_command(req: CommandRequest, ws: WebSocket = None) -> dict:
    t0 = time.monotonic()
    s  = app.state

    history = s.memory.get_recent(req.session_id, n=6)
    s.memory.add(req.session_id, "user", req.text,
                 meta={"gaze": req.gaze_target, "gesture": req.hand_gesture})

    intent_data = await s.llm.classify_intent(
        req.text, req.gaze_target, history, req.pupil_dilation
    )
    intent = intent_data.get("intent", "general_chat")
    params = intent_data.get("params", {})

    log.info(f"[{req.session_id}] intent={intent}")

    if ws:
        await ws.send_json({
            "type": "intent_detected",
            "intent": intent,
            "hud_mode": HUD_MODES.get(intent, "default"),
        })

    # Route to handler
    HANDLERS = {
        "web_search":      _h_search,
        "play_youtube":    _h_youtube,
        "read_email":      _h_read_email,
        "send_email":      _h_send_email,
        "summarize_email": _h_summarize_email,
        "identify_object": _h_identify,
        "weather":         _h_weather,
        "set_reminder":    _h_reminder,
        "translate":       _h_translate,
        "system_status":   _h_status,
        "navigate":        _h_navigate,
        "anchor_content":  _h_anchor,
        # ── Advanced features ────────────────────────────────────
        "swarm_briefing":  _h_swarm,
        "spatial_query":   _h_spatial_query,
        "meeting_summary": _h_meeting_summary,
        "biometrics":      _h_biometrics,
        "predict":         _h_predict,
        # ── v3 features ──────────────────────────────────────────
        "aoi_scan":        _h_aoi,
        "whatsapp":        _h_whatsapp,
        "privacy_scan":    _h_privacy,
        "translate_live":  _h_translate_live,
        "general_chat":    _h_chat,
    }
    handler = HANDLERS.get(intent, _h_chat)
    result  = await handler(params, req, s)

    speech = result.get("speech", "Done.")
    s.memory.add(req.session_id, "assistant", speech, meta={"intent": intent})

    # Stream TTS
    if ws:
        async for chunk in s.voice.synthesize_stream(speech):
            await ws.send_json({"type": "audio_chunk", "data": chunk,
                                "format": "mp3" if not s.voice.__class__.__name__ == "cartesia" else "pcm"})
        await ws.send_json({"type": "audio_end"})

    payload = {
        "type":       "command_result",
        "intent":     intent,
        "hud_mode":   HUD_MODES.get(intent, "default"),
        "speech":     speech,
        "hud_data":   result.get("hud_data", {}),
        "action":     result.get("action"),
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }
    if ws:
        await ws.send_json(payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

async def _h_search(params, req, s):
    q = params.get("query", req.text)
    results = await s.search.search(q)
    summary = await s.llm.summarize_search(q, results)
    return {"speech": summary,
            "hud_data": {"type": "search_panel", "query": q,
                         "cards": results[:4], "summary": summary}}

async def _h_youtube(params, req, s):
    q = params.get("query", req.text)
    video = await s.youtube.find_and_play(q)
    return {"speech": f"Playing {video['title']}.",
            "hud_data": {"type": "media_player", "video": video},
            "action": {"type": "open_youtube", "embed_url": video["embed_url"],
                       "title": video["title"]}}

async def _h_read_email(params, req, s):
    try:
        emails  = await s.gmail.get_recent(params.get("count", 5))
        summary = await s.llm.summarize_emails(emails)
        return {"speech": summary,
                "hud_data": {"type": "email_list", "emails": emails, "summary": summary}}
    except RuntimeError as e:
        return {"speech": str(e),
                "hud_data": {"type": "auth_required", "service": "gmail"}}

async def _h_send_email(params, req, s):
    try:
        draft = await s.llm.draft_email(req.text, params)
        return {"speech": f"Draft ready for {draft.get('to','?')}. Confirm to send.",
                "hud_data": {"type": "email_draft", "draft": draft},
                "action": {"type": "require_confirmation",
                           "confirm_action": "send_email", "payload": draft}}
    except RuntimeError as e:
        return {"speech": str(e), "hud_data": {"type": "auth_required", "service": "gmail"}}

async def _h_summarize_email(params, req, s):
    try:
        emails  = await s.gmail.get_recent(20)
        summary = await s.llm.deep_summarize_emails(emails)
        return {"speech": summary, "hud_data": {"type": "email_summary", "summary": summary}}
    except RuntimeError as e:
        return {"speech": str(e), "hud_data": {"type": "auth_required", "service": "gmail"}}

async def _h_identify(params, req, s):
    gaze = req.gaze_target or params.get("object", "object in view")
    result = await s.vision.identify(gaze, req.image_b64)
    info = await s.search.search(result["label"])
    desc = await s.llm.summarize_search(result["label"], info)
    return {"speech": f"That appears to be {result['label']}. {desc}",
            "hud_data": {"type": "object_scan", "label": result["label"],
                         "confidence": result["confidence"], "info": desc},
            "action": {"type": "scan_effect"}}

async def _h_weather(params, req, s):
    loc = params.get("location", "current location")
    results = await s.search.search(f"weather {loc} today")
    summary = await s.llm.summarize_search(f"weather in {loc}", results)
    return {"speech": summary,
            "hud_data": {"type": "weather_panel", "location": loc, "data": summary}}

async def _h_reminder(params, req, s):
    rem  = params.get("reminder", req.text)
    when = params.get("time", "soon")
    return {"speech": f"Reminder set: {rem} {when}.",
            "hud_data": {"type": "reminder_set", "reminder": rem, "time": when},
            "action": {"type": "set_alarm", "label": rem, "time": when}}

async def _h_translate(params, req, s):
    text = params.get("text", req.text)
    lang = params.get("language", "Spanish")
    result = await s.llm.translate(text, lang)
    return {"speech": result,
            "hud_data": {"type": "translation", "original": text,
                         "translated": result, "language": lang}}

async def _h_status(params, req, s):
    services = {
        "llm":       "online" if os.getenv("OPENROUTER_API_KEY") else "no key",
        "gmail":     "authenticated" if s.gmail.is_authenticated else "not authenticated",
        "youtube":   "online" if os.getenv("YOUTUBE_API_KEY") else "scraping",
        "search":    "google" if os.getenv("GOOGLE_SEARCH_API_KEY") else "duckduckgo",
        "voice_stt": "deepgram" if os.getenv("DEEPGRAM_API_KEY") else "batch",
        "voice_tts": "cartesia" if os.getenv("CARTESIA_API_KEY") else "gTTS",
    }
    summary = "All EDITH systems operational. " + ", ".join(
        f"{k}: {v}" for k, v in services.items()
    )
    return {"speech": summary, "hud_data": {"type": "system_status", "systems": services}}

async def _h_navigate(params, req, s):
    dest = params.get("destination", "destination")
    results = await s.search.search(f"directions to {dest}")
    summary = await s.llm.summarize_search(f"directions to {dest}", results)
    return {"speech": summary,
            "hud_data": {"type": "navigation", "destination": dest, "summary": summary}}

async def _h_anchor(params, req, s):
    label = params.get("label", "Note")
    return {"speech": f"{label} anchored to your current position.",
            "hud_data": {"type": "anchor_placed", "label": label},
            "action": {"type": "place_anchor", "label": label,
                       "position": req.spatial_anchor or {"x":0,"y":0,"z":-1}}}

async def _h_chat(params, req, s):
    history  = s.memory.get_recent(req.session_id, n=8)
    response = await s.llm.chat(req.text, history)
    return {"speech": response, "hud_data": {"type": "chat_bubble", "text": response}}


# ── Advanced Feature Handlers ─────────────────────────────────────────────────

async def _h_swarm(params, req, s):
    """Multi-agent swarm briefing — runs specialists in parallel."""
    result = await s.swarm.run(req.text)
    s.predict.record_command(req.text, "swarm_briefing")
    return result

async def _h_spatial_query(params, req, s):
    """Query world memory for object locations."""
    q      = params.get("query", req.text)
    result = await s.spatial.query(q)
    return {
        "speech":   result["answer"],
        "hud_data": {
            "type":    "spatial_result",
            "answer":  result["answer"],
            "objects": result["results"],
            "stats":   s.spatial.stats(),
        },
    }

async def _h_meeting_summary(params, req, s):
    """Force a meeting/ambient audio summary."""
    summary = await s.ambient.get_summary(force=True)
    if not summary:
        return {"speech": "No conversation recorded yet. Enable ambient mode first.",
                "hud_data": {"type": "chat_bubble", "text": "No ambient audio yet."}}
    return summary

async def _h_biometrics(params, req, s):
    """Return current biometric readings from rPPG."""
    result = s.rppg.estimate(req.session_id)
    if result.get("status") == "collecting":
        speech = f"Collecting biometric data — {result.get('progress_pct',0)}% complete. Keep the camera on your face."
    elif result.get("status") == "ready":
        bpm    = result.get("bpm", 0)
        stress = result.get("stress_pct", 0)
        speech = f"Heart rate: {bpm} BPM. Stress level: {stress}%."
    else:
        speech = "Biometric sensor not active. Send face frames to begin."
    return {
        "speech":   speech,
        "hud_data": {"type": "biometrics", "data": result},
    }

async def _h_predict(params, req, s):
    """Ask EDITH to predict what you'll need next."""
    prediction = await s.predict.predict_next()
    if not prediction:
        return {"speech": "I don't have enough pattern data yet to predict. Keep using me!",
                "hud_data": {"type": "chat_bubble", "text": "Learning your patterns…"}}
    return {
        "speech":   prediction.get("speech",""),
        "hud_data": {"type": "prediction", **prediction},
        "action":   {"type": "suggest_action", "action": prediction.get("action")},
    }


# ─────────────────────────────────────────────────────────────────────────────
# REST ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/command")
async def rest_command(req: CommandRequest):
    """REST fallback when WebSocket unavailable."""
    result = await _execute_command(req)
    return JSONResponse(result)


@app.post("/api/confirm")
async def confirm_action(req: ConfirmRequest):
    """Wrist-tap confirmation handler (e.g., send_email)."""
    s   = app.state
    ws  = s.clients.get(req.session_id)
    msg = "Done."

    if req.action == "send_email":
        try:
            await s.gmail.send(req.data["to"], req.data["subject"], req.data["body"])
            msg = f"Email sent to {req.data['to']}."
        except Exception as e:
            msg = str(e)

    if ws:
        async for chunk in s.voice.synthesize_stream(msg):
            await ws.send_json({"type": "audio_chunk", "data": chunk})
        await ws.send_json({"type": "audio_end"})
        await ws.send_json({"type": "action_confirmed", "action": req.action, "speech": msg})

    return JSONResponse({"status": "ok", "speech": msg})


@app.get("/auth/gmail/start")
async def gmail_auth_start():
    data = await app.state.gmail.start_device_auth()
    return JSONResponse(data)

@app.get("/auth/gmail/status")
async def gmail_auth_status():
    return JSONResponse({
        "authenticated": app.state.gmail.is_authenticated,
        "message": "Gmail ready" if app.state.gmail.is_authenticated else "Not authenticated"
    })

# ── Advanced feature endpoints ────────────────────────────────────────────────

@app.get("/api/spatial/stats")
async def spatial_stats():
    return JSONResponse(app.state.spatial.stats())

@app.post("/api/spatial/query")
async def spatial_query(body: dict):
    result = await app.state.spatial.query(body.get("query",""))
    return JSONResponse(result)

@app.post("/api/rppg/frame")
async def rppg_frame(body: dict):
    """Accept a base64 JPEG face frame for biometric analysis."""
    sid   = body.get("session_id","default")
    ready = app.state.rppg.push_frame(sid, body.get("data",""))
    if ready:
        return JSONResponse({"ready": True, "estimate": app.state.rppg.estimate(sid)})
    return JSONResponse({"ready": False, "frames": "collecting"})

@app.get("/api/rppg/{session_id}")
async def rppg_estimate(session_id: str):
    return JSONResponse(app.state.rppg.estimate(session_id))

@app.post("/api/ambient/utterance")
async def ambient_push(body: dict):
    alerts  = app.state.ambient.push_utterance(body.get("text",""), body.get("speaker","?"))
    summary = await app.state.ambient.get_summary()
    return JSONResponse({"alerts": alerts, "summary": summary})

@app.get("/api/ambient/summary")
async def ambient_summary():
    s = await app.state.ambient.get_summary(force=True)
    return JSONResponse(s or {"status": "no_data"})

@app.get("/api/proactive/state")
async def proactive_state():
    return JSONResponse(app.state.proactive.state)

@app.post("/api/swarm")
async def swarm_run(body: dict):
    result = await app.state.swarm.run(body.get("query","brief me"))
    return JSONResponse(result)

@app.get("/api/predict")
async def predict():
    result = await app.state.predict.predict_next()
    return JSONResponse(result or {"status": "no_prediction"})

@app.get("/api/health")
async def health():
    return JSONResponse({
        "status":    "online",
        "version":   "2.2.0",
        "gmail":     app.state.gmail.is_authenticated,
        "openrouter":bool(os.getenv("OPENROUTER_API_KEY")),
        "spatial_objects": app.state.spatial.stats().get("objects", 0),
        "features":  ["spatial_kg","proactive","rppg","swarm","ambient","predict"],
    })


@app.get("/api/config")
async def get_config():
    """ML2 Android app fetches this to confirm backend is reachable and has keys."""
    key = os.getenv("OPENROUTER_API_KEY","")
    return JSONResponse({
        "has_openrouter_key":  bool(key),
        "has_deepgram_key":    bool(os.getenv("DEEPGRAM_API_KEY","")),
        "has_cartesia_key":    bool(os.getenv("CARTESIA_API_KEY","")),
        "version":             "2.2.0",
    })


@app.post("/api/identify")
async def identify_object(body: dict):
    """
    Called by ML2 EyeTrackingService with a base64 JPEG camera frame.
    Uses OpenRouter vision model to identify the object.
    Returns: {"label": "coffee mug", "confidence": 0.92}
    """
    image_b64   = body.get("data","")
    gaze_hint   = body.get("gaze_target","object")
    result      = await app.state.vision.identify(gaze_hint, image_b64)
    return JSONResponse({
        "label":      result.get("label", gaze_hint),
        "confidence": result.get("confidence", 0.6),
        "category":   result.get("category","unknown"),
    })


@app.post("/api/transcribe")
async def transcribe_audio(body: dict):
    """
    Called by ML2 VoiceService with a complete base64 WAV recording.
    Transcribes using Deepgram (if key set) or Whisper via OpenRouter.
    Returns: {"transcript": "play daft punk on youtube"}
    """
    audio_b64   = body.get("audio_b64","")
    fmt         = body.get("format","wav")
    sample_rate = body.get("sample_rate", 16000)

    if not audio_b64:
        return JSONResponse({"transcript":"","error":"no audio"}, status_code=400)

    import base64
    dg_key = os.getenv("DEEPGRAM_API_KEY","")

    # ── Option 1: Deepgram batch REST (fastest, needs key) ────────────────
    if dg_key:
        try:
            import httpx as _httpx
            audio_bytes = base64.b64decode(audio_b64)
            content_type = "audio/wav" if fmt=="wav" else "audio/raw"
            params = {"model":"nova-3","smart_format":"true"}
            if fmt != "wav":
                params.update({"encoding":"linear16","sample_rate":sample_rate,"channels":"1"})
            async with _httpx.AsyncClient(timeout=20) as c:
                r = await c.post(
                    "https://api.deepgram.com/v1/listen",
                    headers={"Authorization":f"Token {dg_key}","Content-Type":content_type},
                    params=params, content=audio_bytes,
                )
                if r.status_code == 200:
                    text = (r.json().get("results",{})
                              .get("channels",[{}])[0]
                              .get("alternatives",[{}])[0]
                              .get("transcript",""))
                    return JSONResponse({"transcript": text.strip()})
        except Exception as e:
            log.error(f"Deepgram transcribe: {e}")

    # ── Option 2: Whisper via OpenRouter (uses your OpenRouter key) ───────
    or_key = os.getenv("OPENROUTER_API_KEY","")
    if or_key:
        try:
            import httpx as _httpx, base64 as _b64
            audio_bytes = _b64.b64decode(audio_b64)
            # OpenRouter supports Whisper through specific audio models
            # We use a prompt-based workaround: describe audio content
            # Better: use Groq Whisper directly (free tier 7200s/day)
            groq_key = os.getenv("GROQ_API_KEY","")
            if groq_key:
                async with _httpx.AsyncClient(timeout=20) as c:
                    r = await c.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization":f"Bearer {groq_key}"},
                        files={"file":("audio.wav", audio_bytes, "audio/wav")},
                        data={"model":"whisper-large-v3-turbo","response_format":"json"},
                    )
                    if r.status_code == 200:
                        text = r.json().get("text","").strip()
                        return JSONResponse({"transcript": text})
        except Exception as e:
            log.error(f"Whisper transcribe: {e}")

    # ── No STT available ─────────────────────────────────────────────────
    return JSONResponse({
        "transcript": "",
        "error":      "no_stt_key",
        "hint":       "Add DEEPGRAM_API_KEY or GROQ_API_KEY to backend/.env"
    })


@app.get("/")
async def root():
    """Root — redirect to setup page (lets ML2 user enter IP)."""
    return HTMLResponse(
        '<meta http-equiv="refresh" content="0; url=/setup">'
        '<p>Redirecting to EDITH setup…</p>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", 8000))
    log.info(f"Starting EDITH on {host}:{port}")
    uvicorn.run("server:app", host=host, port=port, reload=False, log_level="info")


# ── v3 Intent Handlers ───────────────────────────────────────────────────────

async def _h_aoi(params, req, s):
    result = await s.aoi.scan(
        image_b64  = req.image_b64 or "",
        gaze_hint  = req.gaze_target or params.get("object","object"),
        session_id = req.session_id,
    )
    return result

async def _h_whatsapp(params, req, s):
    action = params.get("action","check")
    if action == "send":
        ok = await s.whatsapp.send_message(params.get("to",""), params.get("text",""))
        speech = "WhatsApp message sent." if ok else "Failed to send. Check WHATSAPP_TOKEN in .env"
        return {"speech": speech, "hud_data": {"type": "chat_bubble", "text": speech}}
    msgs = s.whatsapp.get_unread()
    if not msgs:
        if not s.whatsapp.is_configured:
            return {"speech": "WhatsApp not connected. Say 'connect WhatsApp' to set up.",
                    "hud_data": {"type": "whatsapp_auth", "configured": False}}
        return {"speech": "No unread WhatsApp messages.",
                "hud_data": {"type": "whatsapp_bubbles", "messages": []}}
    preview = "; ".join(f"{m['name']}: {m['text'][:40]}" for m in msgs[:3])
    return {
        "speech":   f"{len(msgs)} unread messages. {preview}.",
        "hud_data": {"type": "whatsapp_bubbles", "messages": msgs,
                     "unread": s.whatsapp.unread_count},
    }

async def _h_privacy(params, req, s):
    result = await s.privacy.scan(req.image_b64 or "", force=True)
    return result

async def _h_translate_live(params, req, s):
    action = params.get("action","start")
    lang   = params.get("language", os.getenv("USER_LANGUAGE","English"))
    if action == "stop":
        s.translation.stop()
        return {"speech": "Live translation stopped.",
                "hud_data": {"type": "chat_bubble", "text": "Translation off."}}
    s.translation.start()
    return {
        "speech":   f"Spatial translation active. Subtitling all speech in {lang}.",
        "hud_data": {"type": "translation_active", "language": lang,
                     "active": True, "speakers": s.translation.speaker_count},
    }


# ── v3 REST Endpoints ─────────────────────────────────────────────────────────

@app.post("/api/aoi/scan")
async def aoi_scan(body: dict):
    result = await app.state.aoi.scan(
        image_b64  = body.get("data",""),
        gaze_hint  = body.get("gaze_target","object"),
        session_id = body.get("session_id","default"),
    )
    return JSONResponse(result)

@app.get("/auth/whatsapp/start")
async def whatsapp_auth_start(request: Request):
    server_url = str(request.base_url).rstrip("/")
    payload    = app.state.whatsapp.generate_qr_payload(server_url)
    return JSONResponse(payload)

@app.get("/auth/whatsapp/callback")
async def whatsapp_callback(token: str = ""):
    return HTMLResponse(
        "<html><body style='background:#000408;color:#00f5ff;font-family:monospace;"
        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
        "<div style='text-align:center'>"
        "<h1 style='font-size:48px;letter-spacing:10px'>E·D·I·T·H</h1>"
        "<p style='letter-spacing:4px'>WhatsApp connected successfully.</p>"
        "<p style='letter-spacing:2px;opacity:.6'>You can close this tab.</p>"
        "</div></body></html>"
    )

@app.post("/webhook/whatsapp")
async def whatsapp_webhook_post(request: Request):
    """Meta webhook for incoming WhatsApp messages."""
    payload   = await request.json()
    new_msgs  = app.state.whatsapp.process_webhook(payload)
    # Push to connected ML2 clients
    for sid, ws in app.state.clients.items():
        try:
            await ws.send_json({"type": "whatsapp_messages", "messages": new_msgs,
                                "unread": app.state.whatsapp.unread_count,
                                "hud_data": {"type":"whatsapp_bubbles","messages":new_msgs}})
        except Exception:
            pass
    return JSONResponse({"status": "ok"})

@app.get("/webhook/whatsapp")
async def whatsapp_webhook_verify(request: Request):
    """Meta webhook verification."""
    p = dict(request.query_params)
    challenge = app.state.whatsapp.verify_webhook(
        p.get("hub.mode",""), p.get("hub.verify_token",""), p.get("hub.challenge","")
    )
    if challenge:
        return HTMLResponse(challenge)
    return JSONResponse({"error": "verification failed"}, status_code=403)

@app.post("/api/whatsapp/send")
async def whatsapp_send(body: dict):
    ok = await app.state.whatsapp.send_message(body.get("to",""), body.get("text",""))
    return JSONResponse({"status": "sent" if ok else "failed"})

@app.get("/api/whatsapp/messages")
async def whatsapp_messages(count: int = 10):
    return JSONResponse({"messages": app.state.whatsapp.get_recent(count),
                         "unread": app.state.whatsapp.unread_count})

@app.post("/api/privacy/scan")
async def privacy_scan_endpoint(body: dict):
    result = await app.state.privacy.scan(body.get("data",""), force=True)
    return JSONResponse(result)

@app.get("/api/privacy/status")
async def privacy_status():
    return JSONResponse(app.state.privacy.last_result)

@app.post("/api/affective/push")
async def affective_push(body: dict):
    sid    = body.get("session_id","default")
    state  = app.state.affective.push(
        sid,
        pupil_l     = body.get("pupil_left", 4.0),
        pupil_r     = body.get("pupil_right", 4.0),
        is_blink    = body.get("is_blink", False),
        fixation_ms = body.get("fixation_ms", 0),
    )
    return JSONResponse(state)

@app.get("/api/affective/{session_id}")
async def affective_state(session_id: str):
    return JSONResponse(app.state.affective.get_state(session_id))

@app.post("/api/translation/utterance")
async def translation_utterance(body: dict):
    result = await app.state.translation.process_utterance(
        transcript       = body.get("text"),
        audio_b64        = body.get("audio_b64"),
        detected_lang    = body.get("lang","en"),
        speaker_id       = body.get("speaker_id","speaker_0"),
        speaker_position = body.get("position"),
    )
    return JSONResponse(result or {"status": "no_result"})

@app.get("/api/translation/subtitles")
async def translation_subtitles():
    return JSONResponse({"subtitles": app.state.translation.get_active_subtitles(),
                         "active": app.state.translation.is_active})

@app.post("/api/translation/start")
async def translation_start():
    app.state.translation.start()
    return JSONResponse({"active": True})

@app.post("/api/translation/stop")
async def translation_stop():
    app.state.translation.stop()
    return JSONResponse({"active": False})
