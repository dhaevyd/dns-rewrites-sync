#!/bin/bash
# DNS Rewrites Sync - Installer
# Works both as a curl | bash one-liner and when run directly from the repo.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/dhaevyd/dns-rewrites-sync/main/dns_sync/scripts/install.sh | bash
#   bash dns_sync/scripts/install.sh

set -euo pipefail

REPO="https://github.com/dhaevyd/dns-rewrites-sync.git"
SERVICE_USER="dns-sync"
CONFIG_DIR="/etc/dns-sync"
DATA_DIR="/var/lib/dns-sync"
SERVICE_FILE="/etc/systemd/system/dns-sync.service"
TIMER_FILE="/etc/systemd/system/dns-sync.timer"

# ── Colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[✔]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
error()   { echo -e "${RED}[✘]${NC} $*" >&2; exit 1; }
step()    { echo -e "\n${YELLOW}──${NC} $*"; }

# ── Sudo helper ────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && SUDO="sudo" || SUDO=""

# ── Detect package manager and install missing deps ────────────────────────
step "Checking dependencies"

install_packages() {
    if command -v apt-get &>/dev/null; then
        $SUDO apt-get update -qq
        $SUDO apt-get install -y -qq "$@"
    elif command -v dnf &>/dev/null; then
        $SUDO dnf install -y -q "$@"
    elif command -v yum &>/dev/null; then
        $SUDO yum install -y -q "$@"
    elif command -v pacman &>/dev/null; then
        $SUDO pacman -Sy --noconfirm "$@"
    else
        error "No supported package manager found (apt/dnf/yum/pacman). Install dependencies manually: $*"
    fi
}

command -v systemctl &>/dev/null || error "systemctl not found — this installer requires systemd."

if ! command -v python3 &>/dev/null; then
    warn "python3 not found — installing..."
    install_packages python3
fi

if ! command -v pip3 &>/dev/null; then
    warn "pip3 not found — installing..."
    if command -v apt-get &>/dev/null; then
        install_packages python3-pip
    elif command -v dnf &>/dev/null || command -v yum &>/dev/null; then
        install_packages python3-pip
    elif command -v pacman &>/dev/null; then
        install_packages python-pip
    fi
fi

if ! command -v git &>/dev/null; then
    warn "git not found — installing..."
    install_packages git
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_OK=$(python3 -c 'import sys; print("yes" if sys.version_info >= (3,8) else "no")')
[[ "$PYTHON_OK" == "yes" ]] || error "Python 3.8+ required (found $PYTHON_VERSION)"
info "Python $PYTHON_VERSION, pip3, git — all good"

# ── Install package ────────────────────────────────────────────────────────
step "Installing dns-rewrites-sync"

pip_install() {
    $SUDO pip3 install "$@" --break-system-packages 2>/dev/null \
        || $SUDO pip3 install "$@"
}

if pip_install dns-rewrites-sync --quiet 2>/dev/null; then
    info "Installed from PyPI"
else
    warn "Not on PyPI yet — installing from source"
    TMP_DIR=$(mktemp -d)
    trap '$SUDO rm -rf "$TMP_DIR" 2>/dev/null || true' EXIT
    git clone --depth 1 "$REPO" "$TMP_DIR" --quiet
    pip_install "$TMP_DIR" --quiet
    info "Installed from source"
fi

# Verify the binary landed somewhere on PATH
command -v dns-sync &>/dev/null || error "dns-sync binary not found on PATH after install"
info "dns-sync $(dns-sync --version 2>/dev/null || echo '(installed)') ready"

# ── System user & directories ──────────────────────────────────────────────
step "Creating system user and directories"

$SUDO useradd --system --no-create-home --home-dir "$DATA_DIR" \
    --shell /usr/sbin/nologin "$SERVICE_USER" 2>/dev/null \
    && info "Created user '$SERVICE_USER'" \
    || info "User '$SERVICE_USER' already exists"

for dir in "$CONFIG_DIR/secrets" "$DATA_DIR"; do
    $SUDO mkdir -p "$dir"
done

$SUDO chown -R "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR" "$DATA_DIR"
$SUDO chmod 750 "$CONFIG_DIR" "$CONFIG_DIR/secrets" "$DATA_DIR"
info "Directories ready"

# ── Systemd units (embedded so curl|bash works) ────────────────────────────
step "Installing systemd units"

$SUDO tee "$SERVICE_FILE" > /dev/null << 'EOF'
[Unit]
Description=DNS Rewrites Sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=dns-sync
Group=dns-sync
WorkingDirectory=/var/lib/dns-sync
ExecStart=/usr/local/bin/dns-sync sync
StandardOutput=journal
StandardError=journal
EOF

$SUDO tee "$TIMER_FILE" > /dev/null << 'EOF'
[Unit]
Description=Run DNS Rewrites Sync hourly

[Timer]
OnBootSec=2min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF

$SUDO systemctl daemon-reload
$SUDO systemctl enable --now dns-sync.timer
info "Timer enabled (runs 2 min after boot, then every hour)"

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ✅  DNS Rewrites Sync installed!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next steps:"
echo "  1. Init master key:       sudo -u $SERVICE_USER dns-sync init"
echo "  2. Add a hub server:      sudo -u $SERVICE_USER dns-sync add-server"
echo "  3. Add spoke server(s):   sudo -u $SERVICE_USER dns-sync add-server"
echo "  4. Test a dry run:        sudo -u $SERVICE_USER dns-sync sync --dry-run"
echo "  5. Run sync now:          sudo systemctl start dns-sync.service"
echo "  6. Watch logs:            journalctl -u dns-sync.service -f"
echo "  7. Check timer:           systemctl status dns-sync.timer"
echo ""
