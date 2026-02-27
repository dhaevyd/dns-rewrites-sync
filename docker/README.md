# dns-rewrites-sync

A hub-and-spoke DNS record sync tool with a web UI. One server acts as the **hub** (source of truth); all others are **spokes** that stay in sync with it automatically.

Supports Pi-hole, AdGuard Home, Technitium DNS, Cloudflare, OPNsense/pfSense, and Unbound.

## Quick Start

```bash
# 1. Copy and fill in credentials
cp .env.example .env
nano .env

# 2. Create your server config
cp config/config.yaml.example config/config.yaml   # or write from scratch
nano config/config.yaml

# 3. Build and run
docker compose up -d

# 4. Open the dashboard
open http://localhost:5680
```

Default login: set via `DNS_SYNC_ADMIN_PASSWORD_HASH` in `.env`.

---

## Configuration

### `config/config.yaml`

Defines all DNS servers. One server must be `sync_mode: hub`; the rest are `sync_mode: spoke`.

```yaml
servers:
  # Hub — source of truth
  - name: Pihole-main
    type: pihole
    url: http://192.168.1.10:5580
    sync_mode: hub
    enabled: true
    auth:
      password: encrypted:password   # credential looked up from env / secrets/

  # Spoke — synced from hub
  - name: Pihole-secondary
    type: pihole
    url: http://192.168.1.11:5580
    sync_mode: spoke
    enabled: true
    auth:
      password: encrypted:password

  # Technitium spoke
  - name: Technitium-home
    type: technitium
    url: http://192.168.1.20:5380
    sync_mode: spoke
    enabled: true
    auth:
      api_token: encrypted:api_token

  # AdGuard spoke
  - name: AdGuard-home
    type: adguard
    url: http://192.168.1.12
    sync_mode: spoke
    enabled: true
    auth:
      username: encrypted:username
      password: encrypted:password
```

**Supported types:** `pihole` · `technitium` · `adguard` · `cloudflare` · `opnsense` · `unbound` · `generic`

### Credentials

Credentials are resolved in this order:
1. **Environment variable** — `DNS_SYNC_{SERVER_NAME_UPPER}_{FIELD_UPPER}` (hyphens → underscores)
2. **Encrypted file** — `config/secrets/{server}-{field}.enc` (legacy CLI)
3. **Plaintext in config.yaml** — not recommended

The `encrypted:fieldname` marker in `auth:` tells the app to look up `fieldname` via the credential chain. See `.env.example` for all server credential formats.

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
| `generic` | `username`, `password`, `api_token` (any) | A, CNAME |

### Technitium Setup

1. In Technitium web UI: **Administration → API Tokens → Add Token**
2. Grant the token DNS read/write permissions
3. Add to `.env`:
   ```
   DNS_SYNC_TECHNITIUM_HOME_API_TOKEN=your-token-here
   ```
4. Add to `config.yaml`:
   ```yaml
   - name: Technitium-home
     type: technitium
     url: http://192.168.1.20:5380
     sync_mode: spoke
     enabled: true
     auth:
       api_token: encrypted:api_token
   ```

---

## Environment Variables

See `.env.example` for the full reference. Key variables:

| Variable | Description |
|----------|-------------|
| `DNS_SYNC_SECRET_KEY` | Session signing key — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `DNS_SYNC_ADMIN_PASSWORD_HASH` | Bcrypt hash of web UI password |
| `DNS_SYNC_INTERVAL_MINUTES` | Default auto-sync interval (overridden by UI settings) |
| `DNS_SYNC_DISCORD_WEBHOOK_URL` | Discord webhook for sync failure notifications |

---

## Volumes

| Host path | Container path | Purpose |
|-----------|---------------|---------|
| `./config` | `/etc/dns-sync` | `config.yaml`, `master.key`, `secrets/` |
| `./dns-sync-data` | `/var/lib/dns-sync` | `sync.db`, `settings.json` |

---

## Web UI

The dashboard runs on port **5680** by default.

- **Hub card** — shows cache status, A/CNAME record counts, last refresh time. Refresh Hub button queries the hub live and updates the cache.
- **Spoke cards** — show sync status (Synced / Error / Never synced), record counts, last sync time. Per-spoke Sync, Disable, Clear Records, and Remove buttons.
- **Sync All** — refreshes hub cache once, then syncs all enabled spokes.
- **Settings** — configure auto-sync interval and enable/disable the background sync loop.
- **History** — filterable per-spoke sync log with error details.

---

## Sync Behaviour

- On **startup**: hub cache is refreshed, then all enabled spokes are synced.
- On **schedule**: background loop refreshes hub cache then syncs all enabled spokes at the configured interval.
- On **manual sync**: hub cache is refreshed first, then the selected spoke is diffed and updated.
- **Clear Records**: queries the spoke live and deletes every record it finds — useful before decommissioning or resetting a spoke.
- Disabled spokes are skipped in all sync paths.

---

## Common Commands

```bash
# View logs
docker compose logs -f

# Restart
docker compose restart dns-sync

# Rebuild after code changes
docker compose build && docker compose up -d

# Check sync history in DB directly
docker exec dns-sync python3 -c \
  "from dns_sync.db import get_history; [print(r) for r in get_history('/var/lib/dns-sync/sync.db', limit=10)]"

# Generate a new password hash
python3 -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"

# Generate a new session secret
python3 -c "import secrets; print(secrets.token_hex(32))"
```
