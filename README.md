# EDITH-AR-v4 — Project Overview

This repository contains the EDITH AR (v4) application: an Android app built for Magic Leap 2 plus a Python backend with multiple assistant services.

## Key Features
- Android app targetting Magic Leap 2 (ML2) with a WebView UI and backend integration.
- Backend services (FastAPI) providing assistants and integrations:
  - Gmail device-flow authentication and email read/send capabilities (`backend/services/gmail_service.py`).
  - WhatsApp Cloud API integration with graceful fallback for non-business users (`backend/services/whatsapp_service.py`).
  - LLM integration (OpenRouter or other via `OPENROUTER_API_KEY`).
  - Vision, voice, memory, spatial-knowledge services under `backend/services/`.
  - Spatial KG using ChromaDB (`backend/data/spatial_kg/`).
- Deployment and local development helper scripts and docs: `DEPLOYMENT.md`, `.env` template.
- Secrets and runtime tokens are ignored via `.gitignore` (do not commit `.env` or `backend/data/*_tokens.json`).

## Quickstart (local laptop + ML2)
1. Set environment variables in `backend/.env` (copy or create a local `.env`, DO NOT commit it):
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (for Gmail device flow)
   - `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_APP_SECRET` (optional, for WhatsApp Cloud)
   - `OPENROUTER_API_KEY`, other voice/llm keys as needed
2. Start the backend (from repository root):
```
cd backend
python server.py
```
3. Build the Android app (Windows):
```
cd android
.\gradlew.bat assembleDebug
```
4. Install to ML2 using adb (use your local SDK path if needed):
```
adb install -r app/build/outputs/apk/debug/app-debug.apk
```
5. Configure `BACKEND_HOST` in `android/app/src/main/java/com/edith/ml2/MainActivity.kt` to point to your laptop IP so the device can reach the backend.

## Gmail Device-Flow (testing)
1. Ensure `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are present in `backend/.env`.
2. Start backend: `python server.py`.
3. Open in a browser or hit the backend endpoint to start auth:
   - `GET /auth/gmail/start` — returns `user_code` and `verification_url`.
4. On your phone/PC go to `https://google.com/device`, enter the code, and grant access.
5. Verify `backend/data/gmail_tokens.json` is created and `GET /auth/gmail/status` reports authenticated.

## WhatsApp Cloud (notes)
- This project supports the WhatsApp Cloud API but does not require it to run: when WhatsApp credentials are missing the service falls back to no-op responses and helpful HUD hints so the rest of the pipeline keeps working.
- To enable full functionality, populate `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, and `WHATSAPP_APP_SECRET` in `backend/.env` and restart the backend, then follow `GET /auth/whatsapp/start` if needed.

## Important Files & Locations
- Android app: `android/` (build via Gradle)
- Android entry: `android/app/src/main/java/com/edith/ml2/MainActivity.kt` (set `BACKEND_HOST`)
- Backend app: `backend/server.py` (FastAPI app entry)
- Services: `backend/services/*.py` (Gmail, WhatsApp, vision, voice, etc.)
- Tokens and data: `backend/data/` (ignored by git)
- Deployment notes: `DEPLOYMENT.md`

## Safety & Secrets
- Do NOT commit `backend/.env` or any token files. These are ignored by `.gitignore`.

## Reverting or Isolating Changes
- To test changes safely without affecting `main`, create a branch before further edits:
```
git checkout -b test/readme-and-auth
```
- To revert the last pushed commit on `main` (creates a new revert commit):
```
git revert HEAD
git push origin main
```

## Troubleshooting
- If the Android app fails to launch, ensure `applicationId` in `android/app/build.gradle` matches `com.edith.ml2` (remove `applicationIdSuffix` if present).
- If the backend cannot reach external APIs, verify your `.env` keys and network access.

## Contact / Next Steps
- To test Gmail auth end-to-end, run the device-flow steps above and tell me when you have the verification code — I can help monitor the backend while you authorize.

---
Generated and pushed by an assistant to document current features and quickstart steps.
