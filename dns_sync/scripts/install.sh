#!/bin/bash
# One-liner installer for DNS Rewrites Sync

set -e

echo "🔧 Installing DNS Rewrites Sync..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found"
    exit 1
fi

# Install package
pip3 install dns-rewrites-sync

# Create directories
sudo mkdir -p /etc/dns-sync/secrets
sudo mkdir -p /var/lib/dns-sync
sudo mkdir -p /var/log/dns-sync

# Create user
sudo useradd --system --home-dir /var/lib/dns-sync dns-sync 2>/dev/null || true

# Set permissions
sudo chown -R dns-sync:dns-sync /etc/dns-sync /var/lib/dns-sync /var/log/dns-sync
sudo chmod 750 /etc/dns-sync /var/lib/dns-sync /var/log/dns-sync

# Install systemd units
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo cp "$SCRIPT_DIR/dns-sync.service" /etc/systemd/system/dns-sync.service
sudo cp "$SCRIPT_DIR/dns-sync.timer"   /etc/systemd/system/dns-sync.timer

# Reload systemd and enable timer
sudo systemctl daemon-reload
sudo systemctl enable --now dns-sync.timer

echo ""
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Initialize master key: sudo -u dns-sync dns-sync init"
echo "  2. Add your servers:      sudo -u dns-sync dns-sync add-server"
echo "  3. Check timer status:    systemctl status dns-sync.timer"
echo "  4. Run sync immediately:  sudo systemctl start dns-sync.service"
echo "  5. Watch logs:            journalctl -u dns-sync.service -f"
echo ""
echo "Documentation: https://github.com/dhaevyd/dns-rewrites-sync"