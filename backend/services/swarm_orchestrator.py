"""
EDITH Feature 4 — Multi-Agent Swarm Orchestration
==================================================
Instead of one LLM for everything, a coordinated swarm of specialised
agents that run in parallel and synthesise results.

Agents:
  MailAgent     → retrieves + summarises Gmail threads
  SpatialAgent  → queries world memory for location context
  ResearchAgent → fetches + synthesises web search results
  CalendarAgent → surfaces upcoming events + prep context
  WeatherAgent  → current conditions for current location

Orchestrator receives all agent outputs and builds a "Briefing HUD"
— unified, de-duplicated, ranked by urgency.

OpenRouter Tool Calling:
  Each agent call uses the tool-calling API so the LLM can decide
  which sub-agents to invoke based on the user's request.
"""

import os, json, logging, asyncio, time
from typing import Optional
import httpx

log = logging.getLogger("EDITH.Swarm")

KEY  = os.getenv("OPENROUTER_API_KEY", "")
BASE = "https://openrouter.ai/api/v1"

# Orchestrator uses a smart model; sub-agents use fast models
MODEL_ORCHESTRATOR = "anthropic/claude-sonnet-4-5"
MODEL_FAST         = "meta-llama/llama-3.1-8b-instruct"


ORCHESTRATOR_SYSTEM = """You are the EDITH Orchestrator — a master agent that delegates tasks
to a swarm of specialised sub-agents and synthesises their outputs into a unified briefing.

Available agents: mail_agent, spatial_agent, research_agent, calendar_agent, weather_agent.

When the user makes a complex request, decide which agents to invoke in parallel.
After receiving their results, synthesise into a clear, prioritised briefing.
Format: brief spoken summary (2-3 sentences) + structured HUD data."""


# ── Tool definitions ─────────────────────────────────────────────────────────

SWARM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_mail_agent",
            "description": "Fetch and summarise recent Gmail threads relevant to a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type":"string","description":"Topic or filter (e.g. 'meeting tomorrow')"},
                    "count": {"type":"integer","description":"Number of emails to retrieve","default":5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_spatial_agent",
            "description": "Query world memory for locations and status of physical objects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type":"string","description":"Natural language location question"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_research_agent",
            "description": "Search the web and synthesise information on a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type":"string","description":"Research topic or question"},
                    "depth": {"type":"string","enum":["quick","deep"],"default":"quick"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_calendar_agent",
            "description": "Retrieve upcoming calendar events and generate prep briefings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours_ahead": {"type":"integer","description":"Hours ahead to look","default":24}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_weather_agent",
            "description": "Get current weather conditions and forecast.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type":"string","description":"City or 'current'","default":"current"}
                }
            }
        }
    },
]


class SwarmOrchestrator:
    """
    Orchestrates multiple specialised agents via OpenRouter tool calling.
    Agents run in parallel where possible.
    """

    def __init__(self, gmail_svc=None, search_svc=None, spatial_kg=None):
        self._http = httpx.AsyncClient(
            base_url=BASE,
            headers={"Authorization": f"Bearer {KEY}",
                     "HTTP-Referer": "https://edith-ar.local",
                     "X-Title": "EDITH Swarm"},
            timeout=45.0,
        )
        self._gmail   = gmail_svc
        self._search  = search_svc
        self._spatial = spatial_kg
        log.info("SwarmOrchestrator ready")

    async def run(self, user_request: str, context: dict = None) -> dict:
        """
        Main entry point. Given a complex request, orchestrate agents
        and return a unified briefing.
        """
        t0 = time.monotonic()
        log.info(f"Swarm run: '{user_request}'")

        # ── Round 1: Orchestrator decides which agents to invoke ──────
        messages = [
            {"role": "system", "content": ORCHESTRATOR_SYSTEM},
            {"role": "user",   "content": user_request},
        ]

        r = await self._http.post("/chat/completions", json={
            "model":       MODEL_ORCHESTRATOR,
            "messages":    messages,
            "tools":       SWARM_TOOLS,
            "tool_choice": "auto",
            "max_tokens":  500,
        })
        resp = r.json()
        msg  = resp["choices"][0]["message"]

        tool_calls = msg.get("tool_calls", [])
        if not tool_calls:
            # No agents needed — direct answer
            return {
                "speech":      msg.get("content",""),
                "agents_used": [],
                "hud_data":    {"type":"briefing","sections":[]},
                "latency_ms":  int((time.monotonic()-t0)*1000),
            }

        # ── Round 2: Run all chosen agents in parallel ─────────────────
        log.info(f"Agents invoked: {[tc['function']['name'] for tc in tool_calls]}")
        agent_tasks = [
            self._dispatch_agent(tc["function"]["name"],
                                  json.loads(tc["function"]["arguments"]),
                                  tc["id"])
            for tc in tool_calls
        ]
        agent_results = await asyncio.gather(*agent_tasks, return_exceptions=True)

        # ── Round 3: Synthesise results ───────────────────────────────
        messages.append({"role":"assistant","content":None,"tool_calls":tool_calls})
        for res in agent_results:
            if isinstance(res, dict):
                messages.append({
                    "role":         "tool",
                    "tool_call_id": res["tool_call_id"],
                    "content":      json.dumps(res["data"]),
                })

        synth_r = await self._http.post("/chat/completions", json={
            "model":    MODEL_ORCHESTRATOR,
            "messages": messages,
            "max_tokens": 400,
        })
        synth_msg = synth_r.json()["choices"][0]["message"]["content"].strip()

        # Build HUD sections from agent results
        sections = [r["section"] for r in agent_results
                    if isinstance(r, dict) and "section" in r]

        return {
            "speech":      synth_msg,
            "agents_used": [tc["function"]["name"] for tc in tool_calls],
            "sections":    sections,
            "hud_data":    {
                "type":     "swarm_briefing",
                "sections": sections,
                "summary":  synth_msg,
            },
            "latency_ms":  int((time.monotonic()-t0)*1000),
        }

    async def _dispatch_agent(self, name: str, args: dict, tool_call_id: str) -> dict:
        """Dispatch to the right sub-agent and format output."""
        try:
            if name == "run_mail_agent":
                data = await self._mail_agent(args)
                section = {"title":"📧 Email", "items": data.get("summaries",[])}
            elif name == "run_spatial_agent":
                data = await self._spatial_agent(args)
                section = {"title":"📍 World Memory", "items": [data.get("answer","")]}
            elif name == "run_research_agent":
                data = await self._research_agent(args)
                section = {"title":"🔍 Research", "items": data.get("points",[])}
            elif name == "run_calendar_agent":
                data = await self._calendar_agent(args)
                section = {"title":"📅 Calendar", "items": data.get("events",[])}
            elif name == "run_weather_agent":
                data = await self._weather_agent(args)
                section = {"title":"🌤 Weather", "items": [data.get("summary","")]}
            else:
                data = {"error": f"Unknown agent: {name}"}
                section = {"title": name, "items": [str(data)]}
        except Exception as e:
            log.error(f"Agent {name} error: {e}")
            data = {"error": str(e)}
            section = {"title": name, "items": [f"Error: {e}"]}

        return {"tool_call_id": tool_call_id, "data": data, "section": section}

    # ── Sub-agents ────────────────────────────────────────────────────

    async def _mail_agent(self, args: dict) -> dict:
        if not self._gmail or not self._gmail.is_authenticated:
            return {"summaries": ["Gmail not authenticated — say 'read my emails' to connect."]}
        try:
            emails = await self._gmail.get_recent(args.get("count", 5), args.get("query",""))
            r = await self._http.post("/chat/completions", json={
                "model": MODEL_FAST,
                "messages": [{"role":"user","content":
                    f"Summarise these emails in 3 bullets:\n" +
                    "\n".join(f"- {e['from']}: {e['subject']} — {e['snippet']}" for e in emails)}],
                "max_tokens": 200,
            })
            summary = r.json()["choices"][0]["message"]["content"]
            bullets = [l.strip("- ").strip() for l in summary.split("\n") if l.strip()]
            return {"summaries": bullets[:4], "count": len(emails)}
        except Exception as e:
            return {"summaries": [f"Email error: {e}"]}

    async def _spatial_agent(self, args: dict) -> dict:
        if not self._spatial:
            return {"answer": "World memory not available."}
        result = await self._spatial.query(args.get("query","surroundings"))
        return result

    async def _research_agent(self, args: dict) -> dict:
        if not self._search:
            return {"points": ["Search service unavailable."]}
        q       = args.get("query","")
        results = await self._search.search(q, num=5)
        r = await self._http.post("/chat/completions", json={
            "model": MODEL_FAST,
            "messages": [{"role":"user","content":
                f"Summarise these search results about '{q}' in 3 key points:\n" +
                "\n".join(f"- {r.get('title')}: {r.get('snippet')}" for r in results)}],
            "max_tokens": 250,
        })
        text    = r.json()["choices"][0]["message"]["content"]
        points  = [l.strip("- ").strip() for l in text.split("\n") if l.strip()]
        return {"points": points[:4]}

    async def _calendar_agent(self, args: dict) -> dict:
        if not self._gmail or not self._gmail.is_authenticated:
            return {"events": ["Calendar not connected."]}
        try:
            events = await self._gmail.get_calendar(days=1)
            return {"events": [f"{e['title']} at {e['start']}" for e in events]}
        except Exception as e:
            return {"events": [f"Calendar error: {e}"]}

    async def _weather_agent(self, args: dict) -> dict:
        if not self._search:
            return {"summary": "Search unavailable."}
        loc     = args.get("location","Pilani")
        results = await self._search.search(f"weather {loc} today")
        if results:
            return {"summary": results[0].get("snippet","No data")}
        return {"summary": "Weather data unavailable."}
