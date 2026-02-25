#!/bin/bash
# DNS Rewrites Sync - Uninstaller

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✔]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
step()  { echo -e "\n${YELLOW}──${NC} $*"; }

[[ $EUID -ne 0 ]] && SUDO="sudo" || SUDO=""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " DNS Rewrites Sync - Uninstaller"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
read -rp "This will remove dns-sync and all its data. Are you sure? [y/N] " confirm
[[ "${confirm,,}" == "y" ]] || { echo "Aborted."; exit 0; }

# ── Stop and disable systemd units ────────────────────────────────────────
step "Stopping systemd units"

for unit in dns-sync.timer dns-sync.service; do
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
        $SUDO systemctl stop "$unit"
        info "Stopped $unit"
    fi
    if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
        $SUDO systemctl disable "$unit"
        info "Disabled $unit"
    fi
done

for unit_file in /etc/systemd/system/dns-sync.service /etc/systemd/system/dns-sync.timer; do
    if [[ -f "$unit_file" ]]; then
        $SUDO rm -f "$unit_file"
        info "Removed $unit_file"
    fi
done

$SUDO systemctl daemon-reload

# ── Remove package ─────────────────────────────────────────────────────────
step "Removing package"

if command -v dns-sync &>/dev/null; then
    $SUDO pip3 uninstall dns-rewrites-sync -y --break-system-packages 2>/dev/null \
        || $SUDO pip3 uninstall dns-rewrites-sync -y
    info "Package removed"
else
    warn "dns-sync binary not found, skipping pip uninstall"
fi

# ── Remove data and config ─────────────────────────────────────────────────
step "Removing data and config"

read -rp "Delete all config and credentials in /etc/dns-sync? [y/N] " del_config
if [[ "${del_config,,}" == "y" ]]; then
    $SUDO rm -rf /etc/dns-sync
    info "Removed /etc/dns-sync"
else
    warn "Kept /etc/dns-sync (your servers and credentials are safe)"
fi

$SUDO rm -rf /var/lib/dns-sync
info "Removed /var/lib/dns-sync"

# ── Remove system user ─────────────────────────────────────────────────────
step "Removing system user"

if id dns-sync &>/dev/null; then
    $SUDO userdel dns-sync 2>/dev/null
    info "Removed user 'dns-sync'"
fi

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " ✅  dns-sync uninstalled"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
