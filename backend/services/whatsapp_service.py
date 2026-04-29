"""
EDITH Feature: Spatial WhatsApp Messenger
==========================================
WhatsApp Cloud API integration with QR-code device authentication
(no keyboard needed on AR glasses).

Auth Flow:
  1. Backend generates QR code embedding a short-lived token URL
  2. ML2 HUD renders QR as holographic floating panel
  3. User scans with phone → phone opens URL → grants WhatsApp permission
  4. Backend receives webhook → stores session → starts polling messages

Spatial Bubbles:
  Messages rendered as 3D floating bubbles near the sender's position
  (or at spatial anchors if known). Supports:
    - Glance-to-read (gaze focus expands bubble)
    - Voice-to-text reply (micro-gesture triggers record)
    - Quick-reply via radial menu (pre-set responses)

WhatsApp Cloud API docs: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import os, json, logging, time, asyncio, base64, hmac, hashlib
from typing import Optional
import httpx

log = logging.getLogger("EDITH.WhatsApp")

WA_TOKEN    = os.getenv("WHATSAPP_TOKEN", "")         # Meta System User Access Token
WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")     # WhatsApp Business phone number ID
WA_VERIFY   = os.getenv("WHATSAPP_VERIFY_TOKEN", "EDITH2026")
WA_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
WA_BASE     = "https://graph.facebook.com/v19.0"

# In-memory message store (replace with Redis/DB for production)
_messages:    list[dict] = []
_unread_count: int       = 0
_contacts:    dict[str, dict] = {}   # phone → {name, last_seen, position}


class WhatsAppService:
    """
    WhatsApp Cloud API — spatial AR messaging.
    """

    def __init__(self):
        self._http      = httpx.AsyncClient(timeout=15.0)
        self._connected = bool(WA_TOKEN and WA_PHONE_ID)
        self._session_token: Optional[str] = None
        log.info(f"WhatsAppService | connected={self._connected}")

    # ── QR AUTH FLOW ──────────────────────────────────────────────────

    def generate_qr_payload(self, server_url: str) -> dict:
        """
        Generate QR code data for holographic display on ML2.
        User scans this with phone → opens auth URL → grants permission.
        """
        import secrets, qrcode, io
        token  = secrets.token_urlsafe(16)
        self._session_token = token
        url    = f"{server_url}/auth/whatsapp/callback?token={token}"

        # Generate QR as base64 PNG
        try:
            qr  = qrcode.QRCode(version=1, box_size=4, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#00f5ff", back_color="#000408")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qr_b64 = base64.b64encode(buf.getvalue()).decode()
        except ImportError:
            # qrcode not installed — return URL only
            qr_b64 = ""

        return {
            "url":         url,
            "qr_b64":      qr_b64,
            "token":       token,
            "expires_in":  300,
            "instruction": "Scan this QR code with your phone to connect WhatsApp",
        }

    # ── WEBHOOK VERIFICATION ──────────────────────────────────────────

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Meta webhook verification handshake."""
        if mode == "subscribe" and token == WA_VERIFY:
            return challenge
        return None

    def process_webhook(self, payload: dict) -> list[dict]:
        """
        Process incoming WhatsApp webhook event.
        Returns list of new messages to push to ML2 HUD.
        """
        global _unread_count
        new_msgs = []
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    val = change.get("value", {})
                    msgs = val.get("messages", [])
                    contacts = val.get("contacts", [])

                    # Index contacts
                    for c in contacts:
                        phone = c.get("wa_id","")
                        _contacts[phone] = {
                            "name":     c.get("profile",{}).get("name", phone),
                            "phone":    phone,
                            "position": {"x":0,"y":1.5,"z":-2},  # default world pos
                        }

                    for msg in msgs:
                        phone    = msg.get("from","")
                        msg_type = msg.get("type","text")
                        text     = ""

                        if msg_type == "text":
                            text = msg.get("text",{}).get("body","")
                        elif msg_type == "audio":
                            text = "[🎤 Voice message]"
                        elif msg_type == "image":
                            text = "[📷 Image]"
                        elif msg_type == "document":
                            text = "[📎 Document]"

                        contact  = _contacts.get(phone, {"name": phone, "phone": phone,
                                                          "position":{"x":0,"y":1.5,"z":-2}})
                        entry_d  = {
                            "id":        msg.get("id",""),
                            "from":      phone,
                            "name":      contact.get("name", phone),
                            "text":      text,
                            "type":      msg_type,
                            "timestamp": int(msg.get("timestamp", time.time())),
                            "read":      False,
                            "position":  contact.get("position", {"x":0,"y":1.5,"z":-2}),
                        }
                        _messages.append(entry_d)
                        _unread_count += 1
                        new_msgs.append(entry_d)
                        log.info(f"WhatsApp msg from {contact.get('name')}: {text[:50]}")

        except Exception as e:
            log.error(f"Webhook process error: {e}")

        return new_msgs

    # ── MESSAGE OPERATIONS ────────────────────────────────────────────

    async def send_message(self, to: str, text: str) -> bool:
        """Send a WhatsApp message."""
        if not self._connected:
            log.warning("WhatsApp not configured — check WHATSAPP_TOKEN and WHATSAPP_PHONE_ID")
            return False
        try:
            r = await self._http.post(
                f"{WA_BASE}/{WA_PHONE_ID}/messages",
                headers={"Authorization": f"Bearer {WA_TOKEN}",
                         "Content-Type": "application/json"},
                json={
                    "messaging_product": "whatsapp",
                    "to":                to,
                    "type":              "text",
                    "text":              {"body": text},
                },
            )
            r.raise_for_status()
            log.info(f"WhatsApp sent to {to}")
            return True
        except Exception as e:
            log.error(f"WhatsApp send error: {e}")
            return False

    async def send_voice_reply(self, to: str, audio_b64: str) -> bool:
        """Send a voice note reply (recorded from ML2 mic)."""
        if not self._connected:
            return False
        # First upload media
        try:
            audio_bytes = base64.b64decode(audio_b64)
            upload_r = await self._http.post(
                f"{WA_BASE}/{WA_PHONE_ID}/media",
                headers={"Authorization": f"Bearer {WA_TOKEN}"},
                files={"file": ("voice.ogg", audio_bytes, "audio/ogg")},
                data={"messaging_product": "whatsapp"},
            )
            media_id = upload_r.json().get("id","")
            if not media_id:
                return False

            send_r = await self._http.post(
                f"{WA_BASE}/{WA_PHONE_ID}/messages",
                headers={"Authorization": f"Bearer {WA_TOKEN}",
                         "Content-Type": "application/json"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to, "type": "audio",
                    "audio": {"id": media_id},
                },
            )
            send_r.raise_for_status()
            return True
        except Exception as e:
            log.error(f"Voice reply error: {e}")
            return False

    # ── DATA ACCESS ───────────────────────────────────────────────────

    def get_recent(self, count: int = 10) -> list[dict]:
        return list(reversed(_messages[-count:]))

    def get_unread(self) -> list[dict]:
        return [m for m in _messages if not m["read"]]

    def mark_read(self, msg_id: str):
        global _unread_count
        for m in _messages:
            if m["id"] == msg_id and not m["read"]:
                m["read"] = True
                _unread_count = max(0, _unread_count - 1)

    def mark_all_read(self):
        global _unread_count
        for m in _messages:
            m["read"] = True
        _unread_count = 0

    def get_contacts(self) -> list[dict]:
        return list(_contacts.values())

    def update_contact_position(self, phone: str, xyz: dict):
        """Update where this contact is in physical space (from face detection)."""
        if phone in _contacts:
            _contacts[phone]["position"] = xyz

    @property
    def unread_count(self) -> int:
        return _unread_count

    @property
    def is_configured(self) -> bool:
        return self._connected
