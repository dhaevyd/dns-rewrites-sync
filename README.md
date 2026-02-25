# 🔄 DNS Rewrites Sync

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.8+-green)
![Pi-hole](https://img.shields.io/badge/Pi--hole-v6-red)
![AdGuard](https://img.shields.io/badge/AdGuard-Home-blue)
![License](https://img.shields.io/badge/license-MIT-green)

A powerful, secure, and extensible tool to synchronize DNS rewrite entries across multiple DNS servers. Keep your Pi-hole, AdGuard Home, Cloudflare, OPNsense, Unbound, and custom DNS servers in perfect sync.

## ✨ Features

- **🔐 Secure Credential Storage** - Master key encrypted secrets, never stored in config files
- **🌐 Multi-Server Support** - Pi-hole v6+, AdGuard Home, Cloudflare DNS, OPNsense/pfSense, Unbound, and Generic API
- **🔄 Flexible Sync Modes** - Hub & spoke architecture with bidirectional sync
- **🧠 Smart Record Handling** - A/AAAA and CNAME records with duplicate detection
- **🔍 Dry Run Mode** - Preview changes before applying
- **📊 Sync History** - SQLite database tracks all operations
- **🐳 Docker Ready** - Easy container deployment
- **🎯 CLI First** - Simple, scriptable command-line interface

## 🚀 Quick Start

### Installation

```bash
# One-liner installer
curl -sSL https://raw.githubusercontent.com/dhaevyd/dns-rewrites-sync/main/scripts/install.sh | bash

# Or pip install
pip install dns-rewrites-sync

# Or from source
git clone https://github.com/dhaevyd/dns-rewrites-sync.git
cd dns-rewrites-sync
pip install -e .
```

### Initial Setup

```bash
# Initialize master key (first run only)
dns-sync init

# Add your first server
dns-sync add-server

# Check status
dns-sync status

# Run a sync
dns-sync sync
```

## 📋 Supported Server Types

| Server Type | Authentication | Record Support | API Docs |
|-------------|---------------|----------------|----------|
| **Pi-hole v6+** | Password | A, CNAME | [docs.pi-hole.net](https://docs.pi-hole.net/api/) |
| **AdGuard Home** | Username + Password | A, CNAME | [adguard.com/docs/api](https://adguard.com/docs/api.html) |
| **Cloudflare DNS** | API Token + Zone ID | A, CNAME, TXT | [developers.cloudflare.com/api](https://developers.cloudflare.com/api/) |
| **OPNsense/pfSense** | API Key + Secret | A | [docs.opnsense.org/development/api](https://docs.opnsense.org/development/api.html) |
| **Unbound** | API Key (optional) | A, CNAME | [unbound.docs.nlnetlabs.com](https://unbound.docs.nlnetlabs.com/) |
| **Generic API** | Configurable | Configurable | Custom |

## 🎮 Command Reference

```bash
# Server management
dns-sync add-server             # Interactive server addition
dns-sync list-servers           # List all configured servers
dns-sync remove-server <name>    # Remove a server
dns-sync test-server <name>      # Test server connection

# Sync operations
dns-sync sync                    # Run sync (default: all servers)
dns-sync sync --server <name>    # Sync specific server
dns-sync sync --dry-run          # Preview only, no changes

# Status & Monitoring
dns-sync status                  # Show sync status
dns-sync history                 # Show sync history

# Security
dns-sync init                    # Initialize master key
dns-sync change-master-key       # Change master password
```

## 📁 Configuration Files

```
/etc/dns-sync/
├── config.yaml          # Server config (no secrets!)
├── master.key           # Master encryption key (600 permissions)
└── secrets/             # Encrypted credentials (750 permissions)
    ├── server1_password.enc
    ├── server2_username.enc
    └── server2_password.enc

/var/lib/dns-sync/
└── sync.db              # SQLite sync history

/var/log/dns-sync/
└── sync.log             # Sync logs
```

## 🐳 Docker Deployment

```yaml
version: '3.8'

services:
  dns-sync:
    image: ghcr.io/dhaevyd/dns-rewrites-sync:latest
    container_name: dns-sync
    restart: unless-stopped
    network_mode: "host"
    volumes:
      - ./config:/etc/dns-sync
      - ./data:/var/lib/dns-sync
      - ./logs:/var/log/dns-sync
    environment:
      - TZ=UTC
```

## 🔧 Example Configuration

```yaml
# /etc/dns-sync/config.yaml
servers:
  - name: main-pihole
    type: pihole
    url: http://192.168.2.19:5580
    auth:
      password: encrypted:password
    sync_mode: hub
    
  - name: living-adguard
    type: adguard
    url: http://192.168.2.1:8080
    auth:
      username: encrypted:username
      password: encrypted:password
    sync_mode: spoke
    enabled: true
```

## 🤝 Contributing

Contributions welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md)

## 📝 License

MIT License - Free for personal and commercial use.

## ⚠️ Disclaimer

Not officially affiliated with Pi-hole, AdGuard, Cloudflare, or OPNsense.

---

**Made with ❤️ for the homelab community**