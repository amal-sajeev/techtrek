#!/usr/bin/env bash
# ============================================================
#  TechTrek — one-command deploy script
#
#  First run:    chmod +x deploy.sh && ./deploy.sh
#  After that:   ./deploy.sh
#
#  To install as a background service that survives reboots:
#                ./deploy.sh --service
#
#  Environment overrides:
#    PORT=8080 ./deploy.sh          (default 8000)
#    WORKERS=4 ./deploy.sh          (default 2)
# ============================================================
set -euo pipefail

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
WORKERS="${WORKERS:-2}"
INSTALL_SERVICE=false
[[ "${1:-}" == "--service" ]] && INSTALL_SERVICE=true

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
step() { echo -e "\n${CYAN}[$1/$TOTAL_STEPS]${NC} $2"; }
ok()   { echo -e "  ${GREEN}✔${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail() { echo -e "  ${RED}✖ $1${NC}"; exit 1; }

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

if $INSTALL_SERVICE; then TOTAL_STEPS=8; else TOTAL_STEPS=7; fi

echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     TechTrek Deploy Script           ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"

# ── 1. Python ────────────────────────────────────────────────
step 1 "Checking Python …"
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        major=$("$candidate" -c "import sys; print(sys.version_info.major)" 2>/dev/null || echo 0)
        minor=$("$candidate" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo 0)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done
[ -z "$PYTHON" ] && fail "Python 3.9+ is required.\n  Install:  sudo apt update && sudo apt install python3 python3-venv python3-pip"
ok "Found $PYTHON ($version)"

# ── 2. Virtual environment ───────────────────────────────────
step 2 "Setting up virtual environment …"
if [ ! -d "venv" ]; then
    "$PYTHON" -m venv venv
    ok "Created venv/"
else
    ok "venv/ already exists"
fi
# shellcheck disable=SC1091
source venv/bin/activate
ok "Activated venv ($(python --version))"

# ── 3. Dependencies ─────────────────────────────────────────
step 3 "Installing dependencies …"
pip install --upgrade pip -q 2>&1 | tail -1
pip install -r requirements.txt -q 2>&1 | tail -1
ok "All packages installed"

# ── 4. Environment file ─────────────────────────────────────
step 4 "Checking .env …"
if [ ! -f ".env" ]; then
    if [ ! -f ".env.example" ]; then
        fail ".env.example is missing — cannot create .env"
    fi
    cp .env.example .env

    SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
    else
        sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${SECRET}|" .env
    fi
    ok "Created .env from .env.example"
    ok "Generated random SECRET_KEY automatically"
    echo ""
    echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "  ${YELLOW}ACTION REQUIRED:${NC} Edit .env with your real settings:"
    echo ""
    echo -e "    ${CYAN}nano .env${NC}"
    echo ""
    echo -e "  At minimum, set these:"
    echo -e "    • ${GREEN}DATABASE_URL${NC}  — your PostgreSQL connection string"
    echo -e "    • ${GREEN}RAZORPAY_KEY_ID${NC} and ${GREEN}RAZORPAY_KEY_SECRET${NC}"
    echo -e "    • ${GREEN}ADMIN_BOOTSTRAP_EMAIL${NC} — the first admin's email"
    echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  After editing, run ${CYAN}./deploy.sh${NC} again."
    exit 0
else
    ok ".env already exists"
fi

# Validate SECRET_KEY
SK=$(grep -E "^SECRET_KEY=" .env | head -1 | cut -d'=' -f2-)
if [ "${#SK}" -lt 32 ] || [ "$SK" = "replace_with_64_hex_chars_minimum_32" ]; then
    fail "SECRET_KEY in .env is still a placeholder or too short (need ≥32 chars).\n  Fix it:  python -c \"import secrets; print(secrets.token_hex(32))\""
fi
ok "SECRET_KEY is set (${#SK} chars)"

# ── 5. Database connection ───────────────────────────────────
step 5 "Checking database connection …"
python -c "
from app.config import settings
from sqlalchemy import create_engine, text
e = create_engine(settings.database_url)
with e.connect() as c:
    c.execute(text('SELECT 1'))
db_display = settings.database_url.split('@')[-1] if '@' in settings.database_url else '(local db)'
print('  \033[0;32m✔\033[0m Connected to', db_display)
" || fail "Cannot connect to the database. Check DATABASE_URL in .env\n  Make sure PostgreSQL is running and the database exists.\n  Create it:  sudo -u postgres createdb techtrek"

# ── 6. Migrations ────────────────────────────────────────────
step 6 "Running database migrations …"
alembic upgrade head 2>&1 | while IFS= read -r line; do echo "  $line"; done
ok "Database is up to date"

# ── 7/8. Service install (optional) ─────────────────────────
if $INSTALL_SERVICE; then
    step 7 "Installing systemd service …"

    SERVICE_FILE="/etc/systemd/system/techtrek.service"
    VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
    UVICORN="$PROJECT_DIR/venv/bin/uvicorn"
    RUN_USER="$(whoami)"

    if [ "$EUID" -ne 0 ] && ! sudo -n true 2>/dev/null; then
        warn "Need sudo to install the service."
    fi

    sudo tee "$SERVICE_FILE" > /dev/null <<UNIT
[Unit]
Description=TechTrek Web App
After=network.target postgresql.service

[Service]
Type=exec
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$PROJECT_DIR/venv/bin:/usr/local/bin:/usr/bin
ExecStart=$UVICORN app.main:app --host $HOST --port $PORT --workers $WORKERS --proxy-headers --forwarded-allow-ips=*
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

    sudo systemctl daemon-reload
    sudo systemctl enable techtrek
    sudo systemctl restart techtrek

    ok "Service installed and started"
    ok "It will auto-start on reboot"
    echo ""

    step 8 "Verifying service …"
    sleep 2
    if sudo systemctl is-active --quiet techtrek; then
        ok "techtrek service is running"
    else
        warn "Service may still be starting. Check with: sudo systemctl status techtrek"
    fi

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  Deployed as a background service!                      ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${CYAN}App URL:${NC}        http://<your-server-ip>:${PORT}"
    echo ""
    echo -e "  Useful commands:"
    echo -e "    ${CYAN}sudo systemctl status techtrek${NC}    — check if running"
    echo -e "    ${CYAN}sudo systemctl stop techtrek${NC}      — stop the app"
    echo -e "    ${CYAN}sudo systemctl restart techtrek${NC}   — restart the app"
    echo -e "    ${CYAN}sudo journalctl -u techtrek -f${NC}    — view live logs"
    echo ""
    echo -e "  To update later: ${CYAN}git pull && ./deploy.sh --service${NC}"
    echo ""
    exit 0
fi

# ── 7. Launch (foreground) ───────────────────────────────────
step 7 "Starting TechTrek …"
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  TechTrek is starting!                                   ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}App URL:${NC}    http://<your-server-ip>:${PORT}"
echo -e "  ${CYAN}Workers:${NC}    ${WORKERS}"
echo -e "  ${YELLOW}Ctrl+C${NC}     to stop"
echo ""
echo -e "  ${YELLOW}TIP:${NC} To keep it running after you disconnect, use:"
echo -e "       ${CYAN}./deploy.sh --service${NC}"
echo ""

exec uvicorn app.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --proxy-headers \
    --forwarded-allow-ips="*"
