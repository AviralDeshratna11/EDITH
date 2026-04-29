# EDITH AR v2.2 — Deployment Guide

## Quick Start

```bash
# 1. Install backend dependencies
cd backend
pip install -r requirements.txt

# 2. Configure environment
cp backend/.env.example backend/.env
# Edit .env and add OPENROUTER_API_KEY (minimum requirement)

# 3. Start backend
python server.py
# Server runs on http://0.0.0.0:8000

# 4. On ML2: Connect to http://YOUR-LAPTOP-IP:8000
```

---

## Feature Configuration

### ✅ Gmail (Email, Calendar, Send)

**Status**: Optional but fully implemented  
**Auth Method**: Google Device Flow (no browser needed on AR glasses)

#### Setup:

1. **Get Google credentials** (one-time):
   - Go to https://console.cloud.google.com
   - Create a new project named "EDITH"
   - Enable APIs:
     - Gmail API
     - Google Calendar API v3
     - YouTube Data API v3
   - Credentials → Create OAuth 2.0 → Desktop Application
   - Download JSON and extract `client_id` and `client_secret`

2. **Add to `backend/.env`**:
   ```env
   GOOGLE_CLIENT_ID=YOUR_CLIENT_ID
   GOOGLE_CLIENT_SECRET=YOUR_CLIENT_SECRET
   ```

3. **First time authentication** (on ML2):
   - Say: "read my emails" or "send email"
   - EDITH displays a 6-digit code on your HUD
   - On your phone/computer, go to https://google.com/device
   - Enter the code
   - Grant Gmail permissions when prompted
   - ✅ Done! Tokens auto-save locally

4. **Available commands**:
   - "Read my emails"
   - "Send email to [person] saying [message]"
   - "Summarize my emails"
   - "What's my calendar"

#### Troubleshooting:

- **"Gmail not authenticated"**: Run `/auth/gmail/start` endpoint or say "read emails" to trigger device flow
- **Device auth expires after 30 min**: If you don't enter code in time, just try again
- **Missing scopes error**: Delete `backend/data/gmail_tokens.json` and re-authenticate

---

### ❌ WhatsApp (Currently Unavailable)

**Status**: Requires Meta Business Account (not configured for personal use)

**Why it's disabled**:
- WhatsApp Cloud API only works with Meta Business Accounts
- Personal/business personal numbers aren't supported
- Requires phone number verification and approval

**If you get a WhatsApp command**:
- EDITH will gracefully respond: "WhatsApp not configured. Requires Meta Business Account."
- No errors or crashes — the system continues normally

**To enable WhatsApp** (if you get business account later):
1. Set up Meta Business Account
2. Add WhatsApp product → get credentials
3. Add to `backend/.env`:
   ```env
   WHATSAPP_TOKEN=YOUR_TOKEN
   WHATSAPP_PHONE_ID=YOUR_PHONE_ID
   WHATSAPP_APP_SECRET=YOUR_SECRET
   ```
4. Update webhook in Meta dashboard to: `http://YOUR-IP:8000/webhook/whatsapp`

---

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│          ML2 (Magic Leap 2)                         │
│  ┌───────────────────────────────────────────────┐  │
│  │  EyeTracking  | HandTracking | Voice | Camera │  │
│  │        ↓         ↓              ↓        ↓     │  │
│  │  EdithBridge ←→ WebView ←→ WebSocket        │  │
│  └───────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
                         ↑
        ws://YOUR-IP:8000/ws/edith-main
                         ↓
┌──────────────────────────────────────────────────────┐
│   FastAPI Backend (Python) — 0.0.0.0:8000           │
├──────────────────────────────────────────────────────┤
│ ┌─ Core Services ──────────────────────────────────┐ │
│ │ • LLM (OpenRouter)      Intent → Action routing  │ │
│ │ • Voice (Deepgram/gTTS) Speech-to-text/synthesis│ │
│ │ • Search (Google/Duck)  Web information          │ │
│ │ • Vision (OpenRouter)   Object identification    │ │
│ └──────────────────────────────────────────────────┘ │
│ ┌─ Integration Services ───────────────────────────┐ │
│ │ • Gmail (Google OAuth2) ✅ Fully working         │ │
│ │ • YouTube (API)         ✅ Fully working         │ │
│ │ • WhatsApp (Meta)       ❌ Requires business acc │ │
│ │ • Calendar (Google)     ✅ Fully working         │ │
│ └──────────────────────────────────────────────────┘ │
│ ┌─ Advanced Features ──────────────────────────────┐ │
│ │ • Spatial Memory    (object locations)           │ │
│ │ • Proactive Engine  (anticipatory suggestions)   │ │
│ │ • Biometrics (rPPG) (heart rate, stress level)   │ │
│ │ • Ambient Audio     (meeting transcription)      │ │
│ │ • Privacy Scan      (detect cameras/glasses)     │ │
│ │ • Affective UI      (adapts to your stress)      │ │
│ │ • Swarm Agents      (parallel expert queries)    │ │
│ └──────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
         ↑                    ↑
    Google API            OpenRouter API
   (Gmail/YouTube)         (LLM intelligence)
```

---

## Deployment Checklist

### Pre-Launch (One-time)

- [ ] Extract project: `EDITH-AR-v4-COMPLETE/`
- [ ] Python 3.10+ installed (`python --version`)
- [ ] Android Studio + SDK (for APK rebuild if needed)
- [ ] Git configured (`git config --global user.name "..."`)

### Backend Setup (Per machine)

- [ ] Create `.env` from `.env.example`: `cp backend/.env.example backend/.env`
- [ ] Get Google OAuth2 credentials (see Gmail section above)
- [ ] Get OpenRouter API key: https://openrouter.ai
- [ ] Fill in `backend/.env` with at minimum:
  ```env
  OPENROUTER_API_KEY=sk-or-v1-...
  GOOGLE_CLIENT_ID=...
  GOOGLE_CLIENT_SECRET=...
  ```
- [ ] Install packages: `pip install -r requirements.txt`
- [ ] Start server: `python server.py`
- [ ] Test health check: `curl http://localhost:8000/api/health`

### ML2 Setup (Per device)

- [ ] ML2 on same WiFi as laptop
- [ ] Open ML2 browser to: `http://YOUR-LAPTOP-IP:8000`
- [ ] Setup page auto-detects backend
- [ ] Press "LAUNCH EDITH" button
- [ ] Allow microphone permission when prompted
- [ ] **For Gmail**: Say "read my emails" → enter 6-digit code at google.com/device

### Android APK Deployment (if rebuilt)

- [ ] Rebuild in Android Studio: Build → Build Bundle(s) / APK(s)
- [ ] Connect ML2 via USB or WiFi ADB: `adb connect ML2_IP:5555`
- [ ] Install APK: `adb install -r app/build/outputs/apk/debug/app-debug.apk`
- [ ] Launch: `adb shell am start -n com.edith.ml2/.MainActivity`

---

## Testing the Pipeline

### Test 1: Basic Commands (No Auth Required)

```bash
On ML2 HUD or via API:
- "What is the speed of light"         → Web search
- "Play Daft Punk on YouTube"           → YouTube search + playback
- "Translate hello to Spanish"          → Translation
- "System status"                       → Check all services
- "Tell me a joke"                      → LLM chat
```

### Test 2: Gmail (After Auth)

```bash
On ML2 HUD:
- "Read my emails"                      → Lists recent emails
- "Send email to john at example.com"   → Draft appears, confirm with wrist tap
- "Summarize my emails"                 → AI summary of inbox
```

**Debug**:
```bash
curl http://localhost:8000/auth/gmail/status
# Response: {"authenticated": true/false, "message": "..."}
```

### Test 3: WhatsApp (If Configured)

```bash
If Meta Business Account is set up:
- "Check WhatsApp"                      → Lists recent messages
- "Send WhatsApp to +1234567890"        → Send message

If NOT configured (default):
- "Check WhatsApp"                      → "WhatsApp requires business account"
```

### Test 4: Advanced Features

```bash
- "System status"                       → Shows all services + auth state
- "Spatial query: where is the coffee"  → World memory search
- "My biometrics"                       → Heart rate + stress (if camera on)
- "What should I do next"               → Predictive engine
```

---

## Troubleshooting

### Server won't start

```bash
# Check Python version
python --version  # Should be 3.10+

# Verify dependencies
pip install -r requirements.txt

# Check .env is in the right place
ls backend/.env  # Should exist

# Check port 8000 isn't already in use
lsof -i :8000  # macOS/Linux
netstat -an | findstr :8000  # Windows
```

### ML2 can't reach backend

```bash
# 1. Check backend is running
curl http://localhost:8000/api/health

# 2. Get your laptop's local IP
ipconfig  # Windows
ifconfig  # Mac/Linux

# 3. Check firewall on port 8000
# Windows: Windows Defender Firewall → Advanced Settings → 
#          Inbound Rules → New Rule → Port TCP 8000 → Allow

# 4. Ping from ML2 browser
# Open ML2 browser to: http://YOUR-LAPTOP-IP:8000/api/health
# Should show: {"status":"online","version":"2.2.0",...}
```

### Gmail auth fails

```bash
# Delete old tokens and retry
rm backend/data/gmail_tokens.json

# Check credentials in .env
grep GOOGLE_CLIENT backend/.env  # Should not be empty

# Verify credentials are valid
# Go to https://console.cloud.google.com and check project still exists
```

### Commands recognized but no response

```bash
# Check server logs for errors
# Look for lines starting with "ERROR" or "Exception"

# Test REST endpoint directly
curl -X POST http://localhost:8000/api/command \
  -H "Content-Type: application/json" \
  -d '{"text":"hello","session_id":"test"}'
```

### Firewall blocking

**Windows**:
```powershell
netsh advfirewall firewall add rule name="EDITH AR" ^
  dir=in action=allow protocol=TCP localport=8000
```

**Mac**:
```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add python3
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp python3
```

**Linux**:
```bash
sudo ufw allow 8000/tcp
```

---

## Production Deployment

For production on a real server (not ML2):

1. **Use environment-specific config**:
   ```bash
   export OPENROUTER_API_KEY=...
   export GOOGLE_CLIENT_ID=...
   # ... other vars ...
   python server.py  # Uses env vars instead of .env
   ```

2. **Run behind reverse proxy** (Nginx/Caddy):
   ```nginx
   server {
       server_name edith.example.com;
       location / {
           proxy_pass http://localhost:8000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
       }
   }
   ```

3. **Use Gunicorn + Uvicorn**:
   ```bash
   pip install gunicorn
   gunicorn -w 4 -k uvicorn.workers.UvicornWorker server:app
   ```

4. **Enable SSL**:
   - Get cert from Let's Encrypt
   - Configure Nginx/Caddy with cert
   - Update ML2 to use `https://...`

---

## What's Included

### Core Services (Fully Working)
- ✅ **LLM**: Intent routing via OpenRouter (Claude, GPT-4, etc.)
- ✅ **Voice**: Speech-to-text + text-to-speech (Deepgram + ElevenLabs)
- ✅ **Vision**: Object identification from camera frames
- ✅ **Search**: Web search (Google Custom Search or DuckDuckGo)
- ✅ **YouTube**: Video search + playback embed

### Integration Services (Fully Working)
- ✅ **Gmail**: OAuth2 device flow (no browser on AR glasses)
- ✅ **Calendar**: Google Calendar integration
- ✅ **YouTube**: Video discovery

### Integration Services (Gracefully Disabled)
- ❌ **WhatsApp**: Requires Meta Business Account (not configured by default)

### Advanced Features (Fully Working)
- ✅ **Spatial Memory**: Remember object locations in 3D space
- ✅ **Proactive Engine**: Anticipate user needs based on gaze
- ✅ **Biometrics**: Heart rate + stress via face camera (rPPG)
- ✅ **Ambient Audio**: Transcribe and summarize conversations
- ✅ **Privacy Scan**: Detect cameras/glasses in scene
- ✅ **Affective UI**: Adapt colors/typography based on stress level
- ✅ **Swarm Agents**: Parallel expert queries (search, vision, etc.)
- ✅ **Predictive Engine**: Learn your patterns and suggest actions

---

## Performance Notes

- **Latency**: Most commands complete in 1-3 seconds
- **Concurrent users**: ~10-20 on single laptop (depends on API rate limits)
- **Backend memory**: ~500MB baseline + 50MB per active user
- **ML2 app**: ~150MB RAM, ~300MB storage

---

## Support

- **Issues with Gmail**: Check Google OAuth2 credentials in `backend/.env`
- **Issues with WhatsApp**: This requires Meta Business Account (not configured for personal use)
- **General issues**: Check `backend/server.py` logs for errors
- **API reference**: See `EDITH-AR-v4-COMPLETE/backend/services/` for detailed docs

---

## Version History

- **v2.2.0** (Current): Gmail device flow, graceful WhatsApp disable, enhanced error messages
- **v2.1.0**: Core features, spatial memory, voice integration
- **v2.0.0**: Initial XRCC 2026 release

---

**Last Updated**: April 29, 2026  
**For Questions**: See ML2_CONNECTION_GUIDE.txt
