"""
EDITH Gmail Service — OAuth 2.0 Device Flow
============================================
Works on AR glasses because it doesn't need a browser.
User gets a code displayed on the HUD, enters it on their phone.
"""
import os, json, asyncio, logging, time, base64
from pathlib import Path
from email.mime.text import MIMEText
import httpx

log = logging.getLogger("EDITH.Gmail")

CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
TOKEN_FILE    = Path("data/gmail_tokens.json")
SCOPES = ("https://www.googleapis.com/auth/gmail.readonly "
          "https://www.googleapis.com/auth/gmail.send "
          "https://www.googleapis.com/auth/gmail.modify "
          "https://www.googleapis.com/auth/calendar.readonly")


class GmailService:
    def __init__(self):
        self._http   = httpx.AsyncClient(timeout=15.0)
        self._tokens: dict = {}
        self._load_tokens()
        status = "authenticated" if self._tokens else "not authenticated"
        log.info(f"GmailService ready | {status}")

    # ── Device Flow ──────────────────────────────────────────────────────────

    async def start_device_auth(self) -> dict:
        """Returns user_code + URL to show on EDITH HUD."""
        if not CLIENT_ID:
            return {"error": "GOOGLE_CLIENT_ID not set in .env",
                    "user_code": "CONFIG-ERROR",
                    "verification_url": "https://console.cloud.google.com"}
        r = await self._http.post(
            "https://oauth2.googleapis.com/device/code",
            data={"client_id": CLIENT_ID, "scope": SCOPES},
        )
        data = r.json()
        if "error" in data:
            log.error(f"Device auth error: {data}")
            return data
        asyncio.create_task(
            self._poll_token(data["device_code"], data.get("interval", 5))
        )
        return {
            "user_code":        data["user_code"],
            "verification_url": data["verification_url"],
            "expires_in":       data.get("expires_in", 1800),
        }

    async def _poll_token(self, device_code: str, interval: int):
        deadline = time.time() + 1800
        while time.time() < deadline:
            await asyncio.sleep(interval)
            r = await self._http.post(
                "https://oauth2.googleapis.com/token",
                data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                      "device_code": device_code,
                      "grant_type": "urn:ietf:params:oauth:grant-type:device_code"},
            )
            d = r.json()
            if "access_token" in d:
                self._tokens = {
                    "access_token":  d["access_token"],
                    "refresh_token": d.get("refresh_token", ""),
                    "expires_at":    time.time() + d.get("expires_in", 3600),
                }
                self._save_tokens()
                log.info("✅ Gmail authenticated!")
                return
            if d.get("error") not in ("authorization_pending", "slow_down"):
                log.error(f"Gmail auth failed: {d}")
                return

    # ── Token management ─────────────────────────────────────────────────────

    async def _token(self) -> str:
        if not self._tokens:
            raise RuntimeError("Gmail not authenticated. Use /auth/gmail/start")
        if time.time() >= self._tokens.get("expires_at", 0) - 60:
            await self._refresh()
        return self._tokens["access_token"]

    async def _refresh(self):
        r = await self._http.post(
            "https://oauth2.googleapis.com/token",
            data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                  "refresh_token": self._tokens["refresh_token"],
                  "grant_type": "refresh_token"},
        )
        d = r.json()
        if "access_token" in d:
            self._tokens["access_token"] = d["access_token"]
            self._tokens["expires_at"]   = time.time() + d.get("expires_in", 3600)
            self._save_tokens()
        else:
            raise RuntimeError(f"Token refresh failed: {d}")

    # ── Email operations ──────────────────────────────────────────────────────

    async def get_recent(self, count: int = 5, query: str = "") -> list:
        tok  = await self._token()
        hdrs = {"Authorization": f"Bearer {tok}"}
        r    = await self._http.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=hdrs, params={"maxResults": count, "q": query or "in:inbox"},
        )
        r.raise_for_status()
        ids  = r.json().get("messages", [])
        emails = await asyncio.gather(
            *[self._fetch(m["id"], hdrs) for m in ids], return_exceptions=True
        )
        return [e for e in emails if isinstance(e, dict)]

    async def _fetch(self, mid: str, hdrs: dict) -> dict:
        r = await self._http.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}",
            headers=hdrs,
            params={"format": "metadata",
                    "metadataHeaders": ["From", "Subject", "Date"]},
        )
        r.raise_for_status()
        d = r.json()
        h = {x["name"]: x["value"] for x in d.get("payload", {}).get("headers", [])}
        return {"id": mid, "from": h.get("From", "Unknown"),
                "subject": h.get("Subject", "(no subject)"),
                "date": h.get("Date", ""),
                "snippet": d.get("snippet", ""),
                "threadId": d.get("threadId", "")}

    async def send(self, to: str, subject: str, body: str) -> dict:
        tok = await self._token()
        msg = MIMEText(body)
        msg["to"] = to; msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        r = await self._http.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            json={"raw": raw},
        )
        r.raise_for_status()
        log.info(f"Email sent to {to}")
        return {"status": "sent", "to": to, "subject": subject}

    async def get_calendar(self, days: int = 1) -> list:
        from datetime import datetime, timezone, timedelta
        tok = await self._token()
        now = datetime.now(timezone.utc)
        r = await self._http.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {tok}"},
            params={"timeMin": now.isoformat(), "timeMax": (now+timedelta(days=days)).isoformat(),
                    "singleEvents": "true", "orderBy": "startTime", "maxResults": 10},
        )
        return [{"title": e.get("summary","No title"),
                 "start": e.get("start",{}).get("dateTime",""),
                 "location": e.get("location","")}
                for e in r.json().get("items", [])]

    @property
    def is_authenticated(self) -> bool:
        return bool(self._tokens.get("access_token"))

    def _save_tokens(self):
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps(self._tokens))

    def _load_tokens(self):
        if TOKEN_FILE.exists():
            try:
                self._tokens = json.loads(TOKEN_FILE.read_text())
            except Exception:
                self._tokens = {}
