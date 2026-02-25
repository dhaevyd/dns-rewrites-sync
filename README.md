# 🔄 DNS Rewrites Sync

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.8+-green)
![Pi-hole](https://img.shields.io/badge/Pi--hole-v6-red)
![AdGuard](https://img.shields.io/badge/AdGuard-Home-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A tool to synchronize DNS rewrite entries across multiple DNS servers. Keep your Pi-hole, AdGuard Home, Cloudflare, OPNsense, Unbound, and custom DNS servers in sync using a hub-and-spoke model.

## ✨ Features

- **🔐 Secure Credential Storage** - Master key encrypted secrets, never stored in config files
- **🌐 Multi-Server Support** - Pi-hole v6+, AdGuard Home, Cloudflare DNS, OPNsense/pfSense, Unbound, and Generic API
- **🔄 Hub & Spoke Sync** - One server is the source of truth; all spokes are kept in sync with it
- **🧠 Smart Record Handling** - A and CNAME records with duplicate detection
- **🔍 Dry Run Mode** - Preview changes before applying
- **🎯 CLI First** - Simple, scriptable command-line interface
- **🖥️ Systemd Native** - Runs as a systemd service with an hourly timer

## 🚀 Quick Start

### Installation

```bash
# One-liner installer (requires sudo)
curl -sSL https://raw.githubusercontent.com/dhaevyd/dns-rewrites-sync/main/dns_sync/scripts/install.sh | bash

# Or from source
git clone https://github.com/dhaevyd/dns-rewrites-sync.git
cd dns-rewrites-sync
pip install -e .
```

### Initial Setup

```bash
# Initialize master key (first run only — interactive)
sudo -u dns-sync dns-sync init

# Add your hub server (source of truth)
sudo -u dns-sync dns-sync add-server

# Add one or more spoke servers (targets)
sudo -u dns-sync dns-sync add-server

# Preview what would change
sudo -u dns-sync dns-sync sync --dry-run

# Run a sync
sudo systemctl start dns-sync.service
```

## 📋 Supported Server Types

| Server Type | Authentication | Record Support |
|-------------|---------------|----------------|
| **Pi-hole v6+** | Password | A, CNAME |
| **AdGuard Home** | Username + Password | A, CNAME |
| **Cloudflare DNS** | API Token + Zone ID | A, CNAME, TXT |
| **OPNsense/pfSense** | API Key + Secret | A |
| **Unbound** | API Key (optional) | A, CNAME |
| **Generic API** | Configurable | Configurable |

## 🎮 Command Reference

```bash
# Server management
dns-sync add-server              # Interactive server addition
dns-sync list-servers            # List all configured servers
dns-sync remove-server <name>    # Remove a server
dns-sync test-server <name>      # Test server connection

# Sync operations
dns-sync sync                    # Sync all spokes from hub
dns-sync sync --server <name>    # Sync a specific spoke
dns-sync sync --dry-run          # Preview only, no changes

# Status
dns-sync status                  # Show connection status and record counts

# Security
dns-sync init                    # Initialize master key
```

## 📁 Configuration Files

```
/etc/dns-sync/
├── config.yaml          # Server list (no secrets stored here)
├── master.key           # Derived encryption key (600 permissions)
├── master.key.salt      # PBKDF2 salt (600 permissions)
└── secrets/             # Encrypted credentials (750 permissions)
    ├── <server>_password.enc
    ├── <server>_username.enc
    └── <server>_api_token.enc

/var/lib/dns-sync/       # Service working directory
```

## 🔧 Example Configuration

```yaml
# /etc/dns-sync/config.yaml
servers:
  - name: main-pihole
    type: pihole
    url: http://192.168.1.10:80
    auth:
      password: encrypted:password
    sync_mode: hub

  - name: backup-adguard
    type: adguard
    url: http://192.168.1.11:3000
    auth:
      username: encrypted:username
      password: encrypted:password
    sync_mode: spoke
    enabled: true

  - name: router-opnsense
    type: opnsense
    url: https://192.168.1.1
    auth:
      api_key: encrypted:api_key
      api_secret: encrypted:api_secret
    sync_mode: spoke
    enabled: true
```

> Credentials are never written to config.yaml — they're stored encrypted under `/etc/dns-sync/secrets/` and referenced by the `encrypted:<field>` sentinel.

## 🖥️ Running as a Service

The installer sets up a systemd service and hourly timer automatically.

```bash
# Check timer (fires 2 min after boot, then every hour)
systemctl status dns-sync.timer

# Trigger a manual sync
sudo systemctl start dns-sync.service

# Watch logs
journalctl -u dns-sync.service -f
```

## 🛠️ Development

```bash
git clone https://github.com/dhaevyd/dns-rewrites-sync.git
cd dns-rewrites-sync
python3 -m venv venv && source venv/bin/activate
pip install -e .
pip install pytest
pytest -v
```

## 📝 License

MIT License - Free for personal and commercial use.

## ⚠️ Disclaimer

Not officially affiliated with Pi-hole, AdGuard, Cloudflare, or OPNsense.

---

**Made with ❤️ for the homelab community**
