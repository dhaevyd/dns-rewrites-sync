# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
# For dev tools (pytest, black, mypy, flake8):
pip install pytest pytest-cov black mypy flake8 bandit
```

## Common Commands

```bash
# Format, lint, type-check
black dns_sync/
flake8 dns_sync/
mypy dns_sync/

# Tests
pytest tests/ -v
pytest tests/test_servers.py::TestClassName::test_method -v  # single test
pytest --cov=dns_sync tests/ --cov-report=html

# Security audit
bandit -r dns_sync/

# Build package
python setup.py sdist bdist_wheel
```

## Architecture

The tool syncs DNS rewrite records (A/CNAME) across multiple DNS servers using a hub-and-spoke model.

```
CLI (cli.py / argparse)
  → ConfigManager (config.py) — reads /etc/dns-sync/config.yaml
  → SecretsManager (secrets.py) — master-key-encrypted creds in /etc/dns-sync/secrets/
  → create_server() factory (server.py) — dispatches to typed implementations
      → servers/pihole.py, adguard.py, cloudflare.py, opnsense.py, unbound.py, generic.py
```

**Two base classes exist** (important distinction):
- `dns_sync/server.py` — simple `DNSServer` ABC; the `create_server()` factory lives here; server implementations inherit from this
- `dns_sync/servers/base.py` — enhanced `DNSServer` with `DNSRecord` dataclass, retry logic (`_request_with_retry`), and `sync_records()` orchestration; not yet wired into the factory

The registry (`registry.py`) is a pure-data `SERVER_TYPES` dict mapping type keys (e.g. `"pihole"`) to metadata: auth field definitions, class name, module path, supported record types.

## Adding a New Server Type

1. Create `dns_sync/servers/<name>.py` — inherit from `dns_sync.server.DNSServer` and implement `test_connection()`, `get_records()`, `add_record()`, `delete_record()`
2. Register in `registry.py` → `SERVER_TYPES` dict
3. Add an `elif` branch in `server.py` → `create_server()`
4. Add unit tests in `tests/test_servers.py`

## Key Data Paths at Runtime

| Path | Purpose |
|------|---------|
| `/etc/dns-sync/config.yaml` | Server list (no secrets) |
| `/etc/dns-sync/master.key` + `.salt` | PBKDF2-derived Fernet key |
| `/etc/dns-sync/secrets/<server>_<field>.enc` | Per-credential encrypted files |
| `/var/lib/dns-sync/sync.db` | SQLite sync history (planned) |

## Credential Encoding Convention

In `config.yaml`, auth fields use `encrypted:<field_name>` as a sentinel. `DNSServer._load_credentials()` detects this prefix and fetches the real value from `SecretsManager`. When adding a server programmatically, store the sentinel in config and call `secrets.set_credential(server_name, field, value)`.

## Sync Mode

Servers are configured as `hub` or `spoke`. The hub's records are the source of truth; spokes are pushed to match the hub. The actual sync engine (`_cmd_sync` in `cli.py`) is a stub — the logic in `servers/base.py → sync_records()` is the intended implementation but is not yet called.
