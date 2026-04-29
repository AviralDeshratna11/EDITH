#!/usr/bin/env bash
# EDITH AR — Mac/Linux Network Setup
# Usage: chmod +x fix_network.sh && ./fix_network.sh

set -e
CYAN='\033[0;36m'; GRN='\033[0;32m'; YLW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo -e "${CYAN}"
echo "  E.D.I.T.H — Network Setup"
echo "  =========================="
echo -e "${NC}"

# ── Detect OS ────────────────────────────────────────────────
OS="$(uname -s)"

# ── Get local IP ─────────────────────────────────────────────
if [[ "$OS" == "Darwin" ]]; then
  LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "unknown")
else
  LOCAL_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v 127 | head -1 || hostname -I | awk '{print $1}')
fi

echo -e "${GRN}Your IP: ${LOCAL_IP}${NC}"
echo ""

# ── Open firewall port 8000 ──────────────────────────────────
echo -e "${YLW}Opening port 8000 in firewall...${NC}"

if [[ "$OS" == "Darwin" ]]; then
  # Mac — allow Python through firewall
  for py in python3 python; do
    PY_PATH=$(which $py 2>/dev/null || true)
    if [[ -n "$PY_PATH" ]]; then
      sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$PY_PATH" 2>/dev/null || true
      sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$PY_PATH" 2>/dev/null || true
      echo -e "  ${GRN}✓ Unblocked $PY_PATH${NC}"
    fi
  done
  echo -e "  ${YLW}Also check: System Settings → Firewall → Options → Python → Allow${NC}"

elif command -v ufw &>/dev/null; then
  sudo ufw allow 8000/tcp
  sudo ufw reload 2>/dev/null || true
  echo -e "  ${GRN}✓ ufw: port 8000 open${NC}"

elif command -v firewall-cmd &>/dev/null; then
  sudo firewall-cmd --permanent --add-port=8000/tcp
  sudo firewall-cmd --reload
  echo -e "  ${GRN}✓ firewalld: port 8000 open${NC}"

else
  echo -e "  ${YLW}No known firewall tool — trying iptables${NC}"
  sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT 2>/dev/null || true
fi

# ── Test server reachability from this machine ───────────────
echo ""
echo -e "${YLW}Testing server...${NC}"
if curl -s --max-time 3 "http://localhost:8000/api/health" > /dev/null 2>&1; then
  echo -e "  ${GRN}✓ Server running on localhost:8000${NC}"
  HEALTH=$(curl -s "http://localhost:8000/api/health")
  echo -e "  ${GRN}  $HEALTH${NC}"
else
  echo -e "  ${RED}✗ Server not running${NC}"
  echo -e "  ${YLW}  Start it: cd backend && python server.py${NC}"
fi

# ── Print the exact URL to type on ML2 ──────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Open this URL in the Magic Leap 2 browser:${NC}"
echo -e ""
echo -e "  ${GRN}http://${LOCAL_IP}:8000/setup${NC}"
echo -e ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Both ML2 and this machine must be on ${YLW}the same WiFi network${NC}."
echo ""
