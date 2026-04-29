#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# EDITH AR — Complete Setup & Deployment Script
# Usage:
#   ./setup.sh          — install deps + start server
#   ./setup.sh deploy   — build & push APK to connected ML2
#   ./setup.sh connect  — connect to ML2 via ADB WiFi
# ═══════════════════════════════════════════════════════════════════
set -e

CYAN='\033[0;36m'; YLW='\033[1;33m'; GRN='\033[0;32m'
RED='\033[0;31m';  NC='\033[0m'

banner() {
  echo -e "${CYAN}"
  echo "  ███████╗██████╗ ██╗████████╗██╗  ██╗"
  echo "  ██╔════╝██╔══██╗██║╚══██╔══╝██║  ██║"
  echo "  █████╗  ██║  ██║██║   ██║   ███████║"
  echo "  ██╔══╝  ██║  ██║██║   ██║   ██╔══██║"
  echo "  ███████╗██████╔╝██║   ██║   ██║  ██║"
  echo "  ╚══════╝╚═════╝ ╚═╝   ╚═╝   ╚═╝  ╚═╝"
  echo -e "  XRCC 2026  |  Magic Leap 2  |  No Unity${NC}"
  echo ""
}

get_local_ip() {
  python3 -c "import socket; s=socket.socket(); s.connect(('8.8.8.8',80)); \
              print(s.getsockname()[0]); s.close()" 2>/dev/null || echo "127.0.0.1"
}

# ── SETUP & RUN SERVER ────────────────────────────────────────────
setup_and_run() {
  banner
  echo -e "${YLW}[1/4] Checking Python 3.11+...${NC}"
  python3 --version || { echo -e "${RED}Python 3.11+ required${NC}"; exit 1; }

  echo -e "${YLW}[2/4] Installing Python packages...${NC}"
  cd "$(dirname "$0")/backend"
  pip install -r requirements.txt -q
  echo -e "${GRN}✓ Packages installed${NC}"

  echo -e "${YLW}[3/4] Setting up .env...${NC}"
  if [ ! -f ".env" ]; then
    cp ../.env.example .env
    echo -e "${RED}⚠  Edit backend/.env and add your OPENROUTER_API_KEY!${NC}"
    echo -e "${RED}   (The server won't do smart things without it)${NC}"
  fi

  mkdir -p data

  LOCAL_IP=$(get_local_ip)
  echo -e "${YLW}[4/4] Local IP detected: ${GRN}${LOCAL_IP}${NC}"

  echo ""
  echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${CYAN}  EDITH Backend starting on http://${LOCAL_IP}:8000     ${NC}"
  echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo ""
  echo -e "  Browser test:  ${GRN}http://${LOCAL_IP}:8000${NC}"
  echo -e "  ML2 browser:   Open URL above on Magic Leap 2 browser"
  echo -e "  ML2 APK test:  Set BACKEND_HOST=${LOCAL_IP} in MainActivity.kt"
  echo ""
  echo -e "  Voice:  Press ${YLW}SPACE${NC} or click ${YLW}ENGAGE${NC} button"
  echo -e "  Gmail:  Say ${YLW}\"read my emails\"${NC} and follow auth prompt"
  echo ""
  python3 server.py
}

# ── BUILD & DEPLOY APK ─────────────────────────────────────────────
deploy_apk() {
  banner
  LOCAL_IP=$(get_local_ip)
  echo -e "${YLW}Building EDITH APK for Magic Leap 2...${NC}"
  cd "$(dirname "$0")/android"

  # Patch BACKEND_HOST in MainActivity
  MAIN="app/src/main/java/com/edith/ml2/MainActivity.kt"
  sed -i "s/const val BACKEND_HOST = \".*\"/const val BACKEND_HOST = \"${LOCAL_IP}\"/" "$MAIN"
  echo -e "${GRN}✓ Backend URL patched to ${LOCAL_IP}${NC}"

  # Build
  echo -e "${YLW}Running Gradle build...${NC}"
  chmod +x gradlew && ./gradlew assembleDebug

  APK="app/build/outputs/apk/debug/app-debug.apk"
  if [ -f "$APK" ]; then
    echo -e "${GRN}✓ APK built: $APK${NC}"
    echo -e "${YLW}Installing to connected ML2...${NC}"
    adb install -r "$APK"
    echo -e "${GRN}✓ Installed! Launch EDITH on ML2.${NC}"
  else
    echo -e "${RED}✗ Build failed. Check Gradle output above.${NC}"
    exit 1
  fi
}

# ── CONNECT ML2 VIA ADB WIFI ──────────────────────────────────────
connect_ml2() {
  banner
  echo -e "${YLW}Magic Leap 2 ADB WiFi Connection${NC}"
  echo ""
  echo "Steps:"
  echo "  1. On ML2: Settings → System → Developer Options → Enable ADB"
  echo "  2. Find ML2 IP: Settings → About → Network"
  echo ""
  read -rp "Enter ML2 IP address: " ML2_IP
  echo -e "${YLW}Connecting to ${ML2_IP}:5555 ...${NC}"
  adb connect "${ML2_IP}:5555"
  sleep 1
  adb devices
  echo ""
  echo -e "${GRN}✓ If ML2 appears above, run: ./setup.sh deploy${NC}"
}

# ── DISPATCH ──────────────────────────────────────────────────────
case "${1:-run}" in
  "deploy")  deploy_apk   ;;
  "connect") connect_ml2  ;;
  *)         setup_and_run;;
esac
