"""FastAPI application"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .config import ConfigManager
from .secrets import SecretsManager
from . import auth, db, notifications, sync as sync_engine

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

_SETTINGS_DEFAULTS = {"interval_minutes": 30, "enabled": True, "theme": "storm"}

_UNIT_MULTIPLIERS = {"minutes": 1, "minute": 1, "mins": 1, "min": 1,
                     "hours": 60, "hour": 60, "hrs": 60, "hr": 60,
                     "days": 1440, "day": 1440}

def _parse_interval(value: str) -> int:
    """Parse '3 mins', '4 hours', '2 days', or plain int string → minutes."""
    value = value.strip()
    parts = value.split()
    if len(parts) == 2:
        try:
            num = int(parts[0])
            multiplier = _UNIT_MULTIPLIERS.get(parts[1].lower(), 1)
            return max(1, num * multiplier)
        except ValueError:
            pass
    try:
        return max(1, int(value))
    except ValueError:
        return 30


def _settings_path(db_path: str) -> str:
    return os.path.join(os.path.dirname(db_path), "settings.json")


def _load_settings(db_path: str) -> dict:
    path = _settings_path(db_path)
    try:
        with open(path) as f:
            data = json.load(f)
        # Merge with defaults so new keys always have values
        return {**_SETTINGS_DEFAULTS, **data}
    except FileNotFoundError:
        raw = os.environ.get("DNS_SYNC_INTERVAL", "30 mins")
        return {**_SETTINGS_DEFAULTS, "interval_minutes": _parse_interval(str(raw))}
    except Exception:
        return dict(_SETTINGS_DEFAULTS)


def _save_settings(db_path: str, settings: dict):
    path = _settings_path(db_path)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, path)

def _load_or_create_secret_key(data_dir: str) -> str:
    """Load persisted secret key from data volume, or generate and save one on first run."""
    import secrets as _secrets
    key_path = os.path.join(data_dir, "secret.key")
    env_key = os.environ.get("DNS_SYNC_SECRET_KEY")
    if env_key:
        return env_key
    if os.path.exists(key_path):
        with open(key_path) as f:
            return f.read().strip()
    key = _secrets.token_hex(32)
    os.makedirs(data_dir, exist_ok=True)
    with open(key_path, "w") as f:
        f.write(key)
    os.chmod(key_path, 0o600)
    logger.info("Generated new secret key → %s", key_path)
    return key


async def _run_hub_sync_cycle(db_path: str, hub_cfgs: list, cfg, secrets):
    """Parallel hub fetch → sequential DB commit → sequential per-hub spoke sync."""
    loop = asyncio.get_running_loop()

    # Fetch all hubs in parallel (HTTP only, no DB writes)
    fetch_results = await asyncio.gather(
        *[loop.run_in_executor(None, sync_engine._fetch_hub_records, hub_cfg, secrets)
          for hub_cfg in hub_cfgs],
        return_exceptions=True,
    )

    # Commit to DB sequentially — avoids SQLite write contention
    for hub_cfg, result in zip(hub_cfgs, fetch_results):
        hub_name = hub_cfg["name"]
        if isinstance(result, Exception):
            logger.error("Hub fetch failed (%s): %s", hub_name, result)
            notifications.notify_hub_unreachable(hub_name, hub_cfg["type"], str(result))
            if db.get_cached_hub_records(db_path, hub_name):
                logger.warning("Using stale cache for hub %s", hub_name)
        else:
            db.save_hub_records(db_path, hub_name, result)
            logger.info("Hub cache refreshed for %s (%d record types)", hub_name, len(result))

    # Sync each hub's spokes sequentially against its cache
    for hub_cfg in hub_cfgs:
        hub_name = hub_cfg["name"]
        hub_records = db.get_cached_hub_records(db_path, hub_name)
        if hub_records is None:
            logger.warning("Spoke sync skipped for hub %s: no cache available", hub_name)
            continue
        spokes = cfg.list_spokes_for_hub(hub_name)
        await loop.run_in_executor(
            None, sync_engine.sync_all_enabled_spokes, db_path, hub_cfg, spokes, secrets
        )


async def _background_sync_loop(app: FastAPI):
    """Periodically refresh hub caches and sync all enabled spokes."""
    while True:
        settings = _load_settings(app.state.db_path)
        interval = max(1, settings.get("interval_minutes", 30))
        enabled = settings.get("enabled", True)

        # Store next sync time so UI can display it
        if enabled:
            next_at = datetime.now(timezone.utc) + timedelta(minutes=interval)
            app.state.next_sync_at = next_at.isoformat(timespec="seconds")
        else:
            app.state.next_sync_at = None

        await asyncio.sleep(interval * 60)

        if not settings.get("enabled", True):
            logger.info("Auto-sync disabled — skipping scheduled sync")
            continue

        cfg = app.state.config
        secrets = app.state.secrets
        db_path = app.state.db_path
        hub_cfgs = cfg.list_hubs()

        if not hub_cfgs:
            logger.info("Background sync skipped: no hub configured")
            continue

        logger.info("Background sync: %d hub(s)", len(hub_cfgs))
        await _run_hub_sync_cycle(db_path, hub_cfgs, cfg, secrets)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_dir = os.environ.get("DNS_SYNC_CONFIG_DIR", "/etc/dns-sync")
    db_path = os.environ.get("DNS_SYNC_DB_PATH", "/var/lib/dns-sync/sync.db")

    admin_password = os.environ.get("DNS_SYNC_ADMIN_PASSWORD")
    if not admin_password:
        raise RuntimeError(
            "DNS_SYNC_ADMIN_PASSWORD is not set. Add it to your .env file."
        )
    import bcrypt as _bcrypt
    admin_hash = _bcrypt.hashpw(admin_password.encode(), _bcrypt.gensalt()).decode()
    del admin_password

    config = ConfigManager(config_dir)
    secrets = SecretsManager(config_dir)

    db.init_db(db_path)

    # Startup: refresh all hub caches and sync spokes
    hub_cfgs = config.list_hubs()
    if hub_cfgs:
        await _run_hub_sync_cycle(db_path, hub_cfgs, config, secrets)
    else:
        logger.warning("Startup sync skipped: no hub configured")

    app.state.config = config
    app.state.secrets = secrets
    app.state.db_path = db_path
    app.state.admin_password_hash = admin_hash
    app.state.next_sync_at = None

    # Start background sync loop
    bg_task = asyncio.create_task(_background_sync_loop(app))

    yield

    # Shutdown: cancel background task cleanly
    bg_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="dns-sync", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
_data_dir = os.path.dirname(os.environ.get("DNS_SYNC_DB_PATH", "/var/lib/dns-sync/sync.db"))
_SECRET_KEY = _load_or_create_secret_key(_data_dir)
app.add_middleware(SessionMiddleware, secret_key=_SECRET_KEY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_servers(request: Request):
    """Return (hub_list, spoke_list) with DB-derived fields attached. Works for both config formats."""
    cfg = request.app.state.config
    db_path = request.app.state.db_path
    hub_names = set()
    hub = []
    for h in cfg.list_hubs():
        h = dict(h)
        h.setdefault("sync_mode", "hub")  # normalise new-format hubs for templates
        h["last_sync"] = db.get_last_sync(db_path, h["name"])
        h["cache_last_updated"] = db.get_cache_last_updated(db_path, h["name"])
        h["cache_record_counts"] = db.get_cache_record_counts(db_path, h["name"])
        hub.append(h)
        hub_names.add(h["name"])
    spokes = []
    for s in cfg.list_servers():
        if s["name"] in hub_names:
            continue
        s = dict(s)
        s["last_sync"] = db.get_last_sync(db_path, s["name"])
        s["spoke_record_counts"] = db.get_spoke_record_counts(db_path, s["name"])
        spokes.append(s)
    return hub, spokes


def _spoke_groups_context(request: Request) -> list:
    """Return hub list each with 'spokes' attached — used by grouped spokes endpoints."""
    cfg = request.app.state.config
    db_path = request.app.state.db_path
    groups = []
    for hub_cfg in cfg.list_hubs():
        hub = dict(hub_cfg)
        hub.setdefault("sync_mode", "hub")
        hub["last_sync"] = db.get_last_sync(db_path, hub["name"])
        hub["cache_last_updated"] = db.get_cache_last_updated(db_path, hub["name"])
        hub["cache_record_counts"] = db.get_cache_record_counts(db_path, hub["name"])
        spokes = []
        for s in cfg.list_spokes_for_hub(hub["name"]):
            s = dict(s)
            s["last_sync"] = db.get_last_sync(db_path, s["name"])
            s["spoke_record_counts"] = db.get_spoke_record_counts(db_path, s["name"])
            spokes.append(s)
        hub["spokes"] = spokes
        groups.append(hub)
    return groups


# ---------------------------------------------------------------------------
# Auth routes (public)
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if auth.is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def login_submit(request: Request):
    form = await request.form()
    password = form.get("password", "")

    if auth.verify_password(password, request.app.state.admin_password_hash):
        request.session["authenticated"] = True
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid password."},
        status_code=401,
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ---------------------------------------------------------------------------
# JSON endpoints (public)
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status(request: Request):
    if (redir := auth.login_required(request)):
        return redir
    servers = request.app.state.config.list_servers()
    return {
        "status": "ok",
        "servers": [
            {
                "name": s["name"],
                "type": s["type"],
                "role": s.get("sync_mode"),
                "enabled": s.get("enabled", True),
            }
            for s in servers
        ],
    }


# ---------------------------------------------------------------------------
# Protected HTML / HTMX endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    if (redir := auth.login_required(request)):
        return redir
    hub, spokes = _split_servers(request)
    history = db.get_history(request.app.state.db_path, limit=50)

    # Aggregate status — exclude disabled spokes
    active_spokes = [s for s in spokes if s.get("enabled", True)]
    ok = sum(1 for s in active_spokes if s.get("last_sync") and s["last_sync"]["status"] == "success")
    errors = sum(1 for s in active_spokes if s.get("last_sync") and s["last_sync"]["status"] == "error")
    never = sum(1 for s in active_spokes if not s.get("last_sync"))
    summary = {"ok": ok, "errors": errors, "never": never, "total": len(active_spokes)}

    settings_ctx = _settings_context(request.app.state.db_path, request.app.state.next_sync_at)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "hub": hub,
            "hubs": _spoke_groups_context(request),
            "spokes": spokes,
            "history": history,
            "summary": summary,
            "selected_server": "",
            "theme": _get_theme(request.app.state.db_path),
            **settings_ctx,
        },
    )


@app.get("/api/servers", response_class=HTMLResponse)
def server_cards(request: Request, role: str = "spoke"):
    if (redir := auth.login_required(request)):
        return redir
    hub, spokes = _split_servers(request)
    servers = spokes if role == "spoke" else hub
    return templates.TemplateResponse(
        "partials/server_cards.html",
        {"request": request, "servers": servers, "theme": _get_theme(request.app.state.db_path)},
    )


@app.get("/api/history", response_class=HTMLResponse)
def history_partial(request: Request, server: str = "", hub: str = ""):
    if (redir := auth.login_required(request)):
        return redir
    cfg = request.app.state.config
    db_path = request.app.state.db_path
    history = db.get_history(db_path, server_name=server or None, hub_name=hub or None, limit=50)
    hub_names = {h["name"] for h in cfg.list_hubs()}
    spokes = [s for s in cfg.list_servers() if s["name"] not in hub_names]
    return templates.TemplateResponse(
        "partials/history.html",
        {
            "request": request,
            "history": history,
            "hubs": cfg.list_hubs(),
            "spokes": spokes,
            "selected_server": server,
            "selected_hub": hub,
            "theme": _get_theme(db_path),
        },
    )


@app.delete("/api/history", response_class=HTMLResponse)
def clear_history_route(request: Request, server: str = "", hub: str = ""):
    if (redir := auth.login_required(request)):
        return redir
    cfg = request.app.state.config
    db_path = request.app.state.db_path
    db.clear_history(db_path, server_name=server or None, hub_name=hub or None)
    history = db.get_history(db_path)
    hub_names = {h["name"] for h in cfg.list_hubs()}
    spokes = [s for s in cfg.list_servers() if s["name"] not in hub_names]
    return templates.TemplateResponse(
        "partials/history.html",
        {
            "request": request,
            "history": history,
            "hubs": cfg.list_hubs(),
            "spokes": spokes,
            "selected_server": "",
            "selected_hub": "",
            "theme": _get_theme(db_path),
        },
    )


@app.post("/api/sync/{server_name}", response_class=HTMLResponse)
async def trigger_sync(server_name: str, request: Request):
    if (redir := auth.login_required(request)):
        return redir

    cfg = request.app.state.config
    secrets = request.app.state.secrets
    db_path = request.app.state.db_path

    spoke_cfg = cfg.get_server(server_name)
    if not spoke_cfg:
        return HTMLResponse(f"<p>Server {server_name!r} not found.</p>", status_code=404)

    # Resolve hub: new format uses hub: field; legacy falls back to sole hub
    hub_name = spoke_cfg.get("hub")
    if hub_name:
        hub_cfg = cfg.get_server(hub_name)
    else:
        hub_cfgs = cfg.list_hubs()
        if len(hub_cfgs) == 1:
            hub_cfg = hub_cfgs[0]
        elif len(hub_cfgs) > 1:
            return HTMLResponse(
                "<p>Spoke has no hub: field and multiple hubs are configured.</p>",
                status_code=400,
            )
        else:
            hub_cfg = None

    if not hub_cfg:
        return HTMLResponse("<p>No hub configured for this spoke.</p>", status_code=400)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, sync_engine.perform_sync, db_path, hub_cfg, spoke_cfg, secrets
    )

    spoke_cfg = dict(spoke_cfg)
    spoke_cfg["last_sync"] = db.get_last_sync(db_path, server_name)
    spoke_cfg["spoke_record_counts"] = db.get_spoke_record_counts(db_path, server_name)
    return templates.TemplateResponse(
        "partials/server_card.html",
        {"request": request, "server": spoke_cfg, "theme": _get_theme(db_path)},
    )


@app.post("/api/sync-all", response_class=HTMLResponse)
async def sync_all(request: Request):
    if (redir := auth.login_required(request)):
        return redir

    cfg = request.app.state.config
    secrets = request.app.state.secrets
    db_path = request.app.state.db_path

    hub_cfgs = cfg.list_hubs()
    if not hub_cfgs:
        return HTMLResponse(
            "<p class='text-red-400 text-sm col-span-full py-4'>No hub configured.</p>",
            status_code=400,
        )

    await _run_hub_sync_cycle(db_path, hub_cfgs, cfg, secrets)

    # Return grouped spokes HTML — same template as /api/servers/spokes poll (M7)
    hub_groups = _spoke_groups_context(request)
    return templates.TemplateResponse(
        "partials/hub_spoke_groups.html",
        {"request": request, "hubs": hub_groups, "theme": _get_theme(db_path)},
    )


@app.post("/api/hub/refresh", response_class=HTMLResponse)
async def hub_refresh(request: Request, hub: str = ""):
    if (redir := auth.login_required(request)):
        return redir

    cfg = request.app.state.config
    secrets = request.app.state.secrets
    db_path = request.app.state.db_path

    if hub:
        hub_cfg = cfg.get_server(hub)
    else:
        hub_cfgs = cfg.list_hubs()
        hub_cfg = hub_cfgs[0] if hub_cfgs else None

    if not hub_cfg:
        return HTMLResponse(
            "<p class='text-red-400 text-sm'>Hub not found.</p>",
            status_code=400,
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, sync_engine.refresh_hub_cache, db_path, hub_cfg, secrets
    )

    hub_cfg = dict(hub_cfg)
    hub_cfg.setdefault("sync_mode", "hub")
    hub_cfg["last_sync"] = db.get_last_sync(db_path, hub_cfg["name"])
    hub_cfg["cache_last_updated"] = db.get_cache_last_updated(db_path, hub_cfg["name"])
    hub_cfg["cache_record_counts"] = db.get_cache_record_counts(db_path, hub_cfg["name"])
    return templates.TemplateResponse(
        "partials/server_card.html",
        {"request": request, "server": hub_cfg, "theme": _get_theme(db_path)},
    )


@app.get("/api/servers/spokes", response_class=HTMLResponse)
def spoke_groups(request: Request):
    """Grouped spokes by hub — used by 30s poll and sync-all response (same template)."""
    if (redir := auth.login_required(request)):
        return redir
    hub_groups = _spoke_groups_context(request)
    return templates.TemplateResponse(
        "partials/hub_spoke_groups.html",
        {"request": request, "hubs": hub_groups, "theme": _get_theme(request.app.state.db_path)},
    )


@app.post("/api/servers/{server_name}/toggle", response_class=HTMLResponse)
def toggle_server(server_name: str, request: Request):
    if (redir := auth.login_required(request)):
        return redir
    cfg = request.app.state.config
    server = cfg.get_server(server_name)
    if not server:
        return HTMLResponse(f"<p>Server {server_name!r} not found.</p>", status_code=404)
    cfg.update_server(server_name, {"enabled": not server.get("enabled", True)})
    server = dict(cfg.get_server(server_name))
    db_path = request.app.state.db_path
    server["last_sync"] = db.get_last_sync(db_path, server_name)
    server["spoke_record_counts"] = db.get_spoke_record_counts(db_path, server_name)
    return templates.TemplateResponse(
        "partials/server_card.html",
        {"request": request, "server": server, "theme": _get_theme(db_path)},
    )


@app.post("/api/servers/{server_name}/clear-records", response_class=HTMLResponse)
async def clear_spoke_records(server_name: str, request: Request):
    if (redir := auth.login_required(request)):
        return redir

    cfg = request.app.state.config
    secrets = request.app.state.secrets
    db_path = request.app.state.db_path

    spoke_cfg = cfg.get_server(server_name)
    if not spoke_cfg:
        return HTMLResponse(f"<p>Server {server_name!r} not found.</p>", status_code=404)

    from .servers import create_server
    from .servers.base import DNSRecord

    def _clear():
        removed = 0
        server = create_server(spoke_cfg["type"], server_name, spoke_cfg, secrets)
        try:
            server.connect()
            # Always query live records — cache may be stale or incomplete
            live_records = server.get_records()
            for record_type, record_set in live_records.items():
                for record_str in record_set:
                    record = (
                        DNSRecord.from_a_string(record_str)
                        if record_type == "A"
                        else DNSRecord.from_cname_string(record_str)
                    )
                    try:
                        if server.delete_record(record):
                            removed += 1
                    except Exception as e:
                        logger.warning("Failed to delete %s from %s: %s", record_str, server_name, e)
        finally:
            server.disconnect()

        db.save_spoke_records(db_path, server_name, {})
        empty = {"added": 0, "removed": removed, "conflicts": 0, "a_records": 0, "cname_records": 0}
        db.record_sync(db_path, server_name, spoke_cfg["type"], "spoke", empty)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _clear)

    server = dict(spoke_cfg)
    server["last_sync"] = db.get_last_sync(db_path, server_name)
    server["spoke_record_counts"] = db.get_spoke_record_counts(db_path, server_name)
    return templates.TemplateResponse(
        "partials/server_card.html",
        {"request": request, "server": server, "theme": _get_theme(db_path)},
    )


@app.delete("/api/servers/{server_name}", response_class=HTMLResponse)
def remove_server(server_name: str, request: Request):
    if (redir := auth.login_required(request)):
        return redir
    request.app.state.config.remove_server(server_name)
    return HTMLResponse("")


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------

def _interval_display(minutes: int) -> tuple[int, str, str]:
    """Return (value, unit, display_label) for a minutes value.

    Converts to the largest whole unit:
      1440 min → (1, "days",    "1 day")
       120 min → (2, "hours",   "2 hours")
        60 min → (1, "hours",   "1 hour")
        30 min → (30, "minutes", "30 minutes")
    """
    if minutes % 1440 == 0:
        val = minutes // 1440
        unit = "days"
        label = f"{val} day" if val == 1 else f"{val} days"
    elif minutes % 60 == 0:
        val = minutes // 60
        unit = "hours"
        label = f"{val} hour" if val == 1 else f"{val} hours"
    else:
        val = minutes
        unit = "minutes"
        label = f"{val} minute" if val == 1 else f"{val} minutes"
    return val, unit, label


def _settings_context(db_path: str, next_sync_at: Optional[str]) -> dict:
    settings = _load_settings(db_path)
    minutes = settings.get("interval_minutes", 30)
    interval_value, interval_unit, interval_label = _interval_display(minutes)
    return {
        "interval_minutes": minutes,
        "interval_value": interval_value,
        "interval_unit": interval_unit,
        "interval_label": interval_label,
        "enabled": settings.get("enabled", True),
        "next_sync_at": next_sync_at,
        "theme": settings.get("theme", "storm"),
    }


@app.get("/api/settings", response_class=HTMLResponse)
def get_settings(request: Request):
    if (redir := auth.login_required(request)):
        return redir
    ctx = _settings_context(request.app.state.db_path, request.app.state.next_sync_at)
    return templates.TemplateResponse(
        "partials/settings.html",
        {"request": request, **ctx},
    )


@app.post("/api/settings", response_class=HTMLResponse)
async def save_settings(request: Request):
    if (redir := auth.login_required(request)):
        return redir
    form = await request.form()
    _UNIT_MULTIPLIERS = {"minutes": 1, "hours": 60, "days": 1440}
    try:
        raw_value = int(form.get("interval_value", 30))
        unit = form.get("unit", "minutes")
        multiplier = _UNIT_MULTIPLIERS.get(unit, 1)
        interval = max(1, min(10080, raw_value * multiplier))  # cap at 7 days
    except (TypeError, ValueError):
        interval = 30
    db_path = request.app.state.db_path
    settings = _load_settings(db_path)
    settings["interval_minutes"] = interval
    _save_settings(db_path, settings)
    # Update next_sync_at
    if settings.get("enabled", True):
        next_at = datetime.now(timezone.utc) + timedelta(minutes=interval)
        request.app.state.next_sync_at = next_at.isoformat(timespec="seconds")
    ctx = _settings_context(db_path, request.app.state.next_sync_at)
    return templates.TemplateResponse(
        "partials/settings.html",
        {"request": request, **ctx},
    )


@app.post("/api/settings/enable", response_class=HTMLResponse)
def enable_sync(request: Request):
    if (redir := auth.login_required(request)):
        return redir
    db_path = request.app.state.db_path
    settings = _load_settings(db_path)
    settings["enabled"] = True
    _save_settings(db_path, settings)
    interval = settings.get("interval_minutes", 30)
    next_at = datetime.now(timezone.utc) + timedelta(minutes=interval)
    request.app.state.next_sync_at = next_at.isoformat(timespec="seconds")
    ctx = _settings_context(db_path, request.app.state.next_sync_at)
    return templates.TemplateResponse(
        "partials/settings.html",
        {"request": request, **ctx},
    )


@app.post("/api/settings/disable", response_class=HTMLResponse)
def disable_sync(request: Request):
    if (redir := auth.login_required(request)):
        return redir
    db_path = request.app.state.db_path
    settings = _load_settings(db_path)
    settings["enabled"] = False
    _save_settings(db_path, settings)
    request.app.state.next_sync_at = None
    ctx = _settings_context(db_path, None)
    return templates.TemplateResponse(
        "partials/settings.html",
        {"request": request, **ctx},
    )


def _get_theme(db_path: str) -> str:
    return _load_settings(db_path).get("theme", "storm")


@app.post("/api/settings/theme")
async def set_theme(request: Request):
    if (redir := auth.login_required(request)):
        return redir
    data = await request.json()
    theme = data.get("theme", "storm")
    if theme not in ("storm", "midnight", "dusk"):
        return JSONResponse({"error": "invalid theme"}, status_code=400)
    db_path = request.app.state.db_path
    settings = _load_settings(db_path)
    settings["theme"] = theme
    _save_settings(db_path, settings)
    return JSONResponse({"ok": True})
