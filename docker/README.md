# dns-rewrites-sync

<p align="center">
  <img src="https://img.shields.io/badge/version-2.2.5-blue?style=flat-square" alt="version"/>
  <img src="https://img.shields.io/badge/image-ghcr.io%2Fdhaevyd%2Fdns--rewrites--sync-blue?style=flat-square&logo=docker" alt="Docker"/>
  <img src="https://img.shields.io/badge/python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/self--hosted-ready-22c55e?style=flat-square" alt="self-hosted"/>
</p>

<p align="center">
  Hub-and-spoke DNS record sync with a web dashboard.<br/>
  One server is the source of truth — everything else stays in sync automatically.
</p>

---

## Features

- **Multi-hub support** — multiple independent hubs, each managing their own spoke group
- **Live dashboard** — real-time sync status, record counts, history per spoke
- **Auto-sync** — configurable background loop (minutes, hours, or days)
- **Diff-based sync** — only adds/removes what changed, never overwrites blindly
- **Notifications** — Discord webhook + SMTP on sync failure or hub unreachable
- **Themes** — Storm, Midnight, Dusk — switchable from the UI
- **Credential-safe** — secrets from env vars only, nothing stored in config

**Supported DNS servers:** Pi-hole v6+ · AdGuard Home · Technitium · Cloudflare · OPNsense/pfSense · Unbound

---

## Architecture

```
                    ┌─────────────────┐
                    │       Hub       │  ← source of truth
                    │  (Pi-hole, etc) │
                    └────────┬────────┘
                             │  cache on startup + on schedule
                    ┌────────▼────────┐
                    │   dns-sync DB   │  ← authoritative_records
                    └────────┬────────┘
              ┌──────────────┼──────────────┐
     ┌────────▼──────┐  ┌────▼────────┐  ┌─▼────────────┐
     │   Spoke A     │  │   Spoke B   │  │   Spoke C    │
     │  (Pi-hole)    │  │  (AdGuard)  │  │ (Technitium) │
     └───────────────┘  └─────────────┘  └──────────────┘
```

Startup → refresh hub cache → sync all enabled spokes → background loop repeats on schedule.
Manual sync always refreshes hub cache first, then diffs the selected spoke.

---

## Quick Start

```bash
# 1. Copy and fill in credentials
cp .env.example .env && chmod 600 .env
nano .env

# 2. Create your server config
cp config/config.example.yaml config/config.yaml
nano config/config.yaml

# 3. Run
docker compose up -d

# 4. Open the dashboard
open http://localhost:5680
```

Set your admin password via `DNS_SYNC_ADMIN_PASSWORD` in `.env`.

---

## Configuration

### `config/config.yaml`

**Single hub (legacy format):**
```yaml
servers:
  - name: Pihole-main
    type: pihole
    url: http://192.168.1.10:80
    sync_mode: hub
    enabled: true
    auth:
      password: encrypted:password

  - name: Pihole-secondary
    type: pihole
    url: http://192.168.1.11:80
    sync_mode: spoke
    enabled: true
    auth:
      password: encrypted:password
```

**Multi-hub format:**
```yaml
hubs:
  - name: pihole-hub
    type: pihole
    url: http://192.168.1.10:80
    enabled: true
    auth:
      password: encrypted:password

servers:
  - name: pihole-spoke
    type: pihole
    hub: pihole-hub        # ← which hub this spoke belongs to
    url: http://192.168.1.11:80
    enabled: true
    auth:
      password: encrypted:password
```

See `config/config.example.yaml` for all server types.

### Credentials

All credentials come from environment variables — nothing is stored in `config.yaml`:

```
DNS_SYNC_{SERVER_NAME}_{FIELD}
```

Hyphens and spaces → underscores, all uppercased.

```bash
# Server named "Pihole-main", field "password"
DNS_SYNC_PIHOLE_MAIN_PASSWORD=your-password

# Server named "adguard-home", fields "username" + "password"
DNS_SYNC_ADGUARD_HOME_USERNAME=admin
DNS_SYNC_ADGUARD_HOME_PASSWORD=your-password
```

The `encrypted:fieldname` marker in `auth:` is just a hint telling the app which env var to look up. See `.env.example` for all formats.

---

## Supported Server Types

| Type | Auth fields | Records |
|------|------------|---------|
| `pihole` | `password` | A, CNAME |
| `technitium` | `api_token` | A, CNAME, AAAA, TXT |
| `adguard` | `username`, `password` | A, CNAME |
| `cloudflare` | `api_token`, `zone_id` | A, CNAME, TXT |
| `opnsense` | `api_key`, `api_secret` | A |
| `unbound` | `api_key` (optional) | A, CNAME |

> **Technitium:** Administration → API Tokens → Add Token. Grant DNS read/write. Token appears in Technitium's access logs (query param by design).

---

## Environment Variables

See `.env.example` for the full reference.

| Variable | Description |
|----------|-------------|
| `DNS_SYNC_ADMIN_PASSWORD` | Web UI admin password |
| `DNS_SYNC_INTERVAL` | Auto-sync interval — `30 mins`, `4 hours`, `1 day` (overridable in UI) |
| `DNS_SYNC_SECRET_KEY` | Session signing key — auto-generated on first run, no need to set |
| `DNS_SYNC_DISCORD_WEBHOOK_URL` | Discord webhook for failure notifications |
| `DNS_SYNC_SMTP_HOST` | SMTP host for email notifications |

---

## Volumes

| Host path | Container path | Purpose |
|-----------|---------------|---------|
| `./config` | `/etc/dns-sync` | `config.yaml` |
| `./dns-sync-data` | `/var/lib/dns-sync` | `sync.db`, `settings.json` |

---

## Web UI

Dashboard on port **5680** by default.

| Section | What it shows |
|---------|--------------|
| **Hub card** | Cache status, A/CNAME record counts, last refresh. Refresh Hub button fetches live. |
| **Spoke cards** | Sync status, record counts, last sync time. Sync / Disable / Clear Records / Remove per spoke. |
| **Sync All** | Refreshes hub cache once, then syncs all enabled spokes. |
| **Settings** | Auto-sync interval, pause/resume background loop. |
| **History** | Filterable per-spoke sync log with error details. |
| **Appearance** | Switch between Storm, Midnight, and Dusk themes. |

---

## Sync Behaviour

- **Startup** — hub cache refreshed, all enabled spokes synced
- **Schedule** — background loop: refresh hub cache → sync all enabled spokes
- **Manual sync** — hub cache refreshed first, then spoke is diffed and updated
- **Diff-based** — only records missing from the spoke are added; only records absent from the hub are removed
- **Disabled spokes** — skipped in all sync paths, grayed out in the UI
- **Clear Records** — queries the spoke live and removes every record; use before decommissioning

---

## Common Commands

```bash
# View logs
docker compose logs -f

# Restart
docker compose restart dns-sync

# Rebuild after code changes
docker compose build && docker compose up -d

# Pull latest image
docker compose pull && docker compose up -d

# Inspect sync history directly
docker exec dns-sync python3 -c \
  "from dns_sync.db import get_history; [print(r) for r in get_history('/var/lib/dns-sync/sync.db', limit=10)]"

# Generate admin password hash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"

# Generate session secret
python3 -c "import secrets; print(secrets.token_hex(32))"
```
