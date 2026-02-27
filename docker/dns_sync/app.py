"""FastAPI application"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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

_SETTINGS_DEFAULTS = {"interval_minutes": 30, "enabled": True}


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
        interval = int(os.environ.get("DNS_SYNC_INTERVAL_MINUTES", 30))
        return {**_SETTINGS_DEFAULTS, "interval_minutes": interval}
    except Exception:
        return dict(_SETTINGS_DEFAULTS)


def _save_settings(db_path: str, settings: dict):
    path = _settings_path(db_path)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, path)

# Fail fast at startup if the session secret key is missing.
_SECRET_KEY = os.environ.get("DNS_SYNC_SECRET_KEY")
if not _SECRET_KEY:
    raise RuntimeError(
        "DNS_SYNC_SECRET_KEY is not set.\n"
        "Generate one with:  python3 -c \"import secrets; print(secrets.token_hex(32))\"\n"
        "Then add it to your .env file."
    )


async def _background_sync_loop(app: FastAPI):
    """Periodically refresh hub cache and sync all enabled spokes."""
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
        servers = cfg.list_servers()
        hub_cfgs = [s for s in servers if s.get("sync_mode") == "hub"]
        spoke_cfgs = [s for s in servers if s.get("sync_mode") != "hub"]

        if not hub_cfgs:
            logger.info("Background sync skipped: no hub configured")
            continue

        loop = asyncio.get_running_loop()
        hub_cfg = hub_cfgs[0]
        logger.info("Background sync: refreshing hub %s", hub_cfg["name"])
        hub_records = await loop.run_in_executor(
            None, sync_engine.refresh_hub_cache, db_path, hub_cfg, secrets
        )
        if hub_records is not None:
            await loop.run_in_executor(
                None, sync_engine.sync_all_enabled_spokes, db_path, hub_cfg, spoke_cfgs, secrets
            )
        else:
            logger.warning("Background sync: hub unreachable and no cache, skipping spoke sync")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_dir = os.environ.get("DNS_SYNC_CONFIG_DIR", "/etc/dns-sync")
    db_path = os.environ.get("DNS_SYNC_DB_PATH", "/var/lib/dns-sync/sync.db")

    admin_hash = os.environ.get("DNS_SYNC_ADMIN_PASSWORD_HASH")
    if not admin_hash:
        raise RuntimeError(
            "DNS_SYNC_ADMIN_PASSWORD_HASH is not set.\n"
            "Generate one with:  "
            "python3 -c \"import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())\"\n"
            "Then add it to your .env file."
        )

    config = ConfigManager(config_dir)
    secrets = SecretsManager(config_dir)

    if not secrets.load_master_key():
        raise RuntimeError(
            f"Failed to load master key from {config_dir}/master.key — "
            "ensure the file exists and DNS_SYNC_CONFIG_DIR is set correctly."
        )

    db.init_db(db_path)

    # Startup: refresh hub cache and sync all enabled spokes
    servers = config.list_servers()
    hub_cfgs = [s for s in servers if s.get("sync_mode") == "hub"]
    spoke_cfgs = [s for s in servers if s.get("sync_mode") != "hub"]
    if hub_cfgs:
        hub_cfg = hub_cfgs[0]
        hub_records = sync_engine.refresh_hub_cache(db_path, hub_cfg, secrets)
        if hub_records is not None:
            sync_engine.sync_all_enabled_spokes(db_path, hub_cfg, spoke_cfgs, secrets)
        else:
            logger.warning("Startup sync skipped: hub unreachable and no cache")
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
app.add_middleware(SessionMiddleware, secret_key=_SECRET_KEY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_servers(request: Request):
    """Return (hub_list, spoke_list) with last_sync (and cache_last_updated for hubs) attached."""
    db_path = request.app.state.db_path
    hub, spokes = [], []
    for s in request.app.state.config.list_servers():
        s = dict(s)
        s["last_sync"] = db.get_last_sync(db_path, s["name"])
        if s.get("sync_mode") == "hub":
            s["cache_last_updated"] = db.get_cache_last_updated(db_path, s["name"])
            s["cache_record_counts"] = db.get_cache_record_counts(db_path, s["name"])
            hub.append(s)
        else:
            s["spoke_record_counts"] = db.get_spoke_record_counts(db_path, s["name"])
            spokes.append(s)
    return hub, spokes


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
    history = db.get_history(request.app.state.db_path)

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
            "spokes": spokes,
            "history": history,
            "summary": summary,
            "selected_server": "",
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
        {"request": request, "servers": servers},
    )


@app.get("/api/history", response_class=HTMLResponse)
def history_partial(request: Request, server: str = ""):
    if (redir := auth.login_required(request)):
        return redir
    history = db.get_history(request.app.state.db_path, server_name=server or None)
    spokes = [s for s in request.app.state.config.list_servers() if s.get("sync_mode") != "hub"]
    return templates.TemplateResponse(
        "partials/history.html",
        {"request": request, "history": history, "spokes": spokes, "selected_server": server},
    )


@app.delete("/api/history", response_class=HTMLResponse)
def clear_history(request: Request, server: str = ""):
    if (redir := auth.login_required(request)):
        return redir
    db.clear_history(request.app.state.db_path, server_name=server or None)
    history = db.get_history(request.app.state.db_path, server_name=None)
    spokes = [s for s in request.app.state.config.list_servers() if s.get("sync_mode") != "hub"]
    return templates.TemplateResponse(
        "partials/history.html",
        {"request": request, "history": history, "spokes": spokes, "selected_server": ""},
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

    hub_cfg = next(
        (s for s in cfg.list_servers() if s.get("sync_mode") == "hub"), None
    )
    if not hub_cfg:
        return HTMLResponse("<p>No hub server configured.</p>", status_code=400)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, sync_engine.perform_sync, db_path, hub_cfg, spoke_cfg, secrets
    )

    spoke_cfg = dict(spoke_cfg)
    spoke_cfg["last_sync"] = db.get_last_sync(db_path, server_name)
    spoke_cfg["spoke_record_counts"] = db.get_spoke_record_counts(db_path, server_name)
    return templates.TemplateResponse(
        "partials/server_card.html",
        {"request": request, "server": spoke_cfg},
    )


@app.post("/api/sync-all", response_class=HTMLResponse)
async def sync_all(request: Request):
    if (redir := auth.login_required(request)):
        return redir

    cfg = request.app.state.config
    secrets = request.app.state.secrets
    db_path = request.app.state.db_path

    hub_cfg = next(
        (s for s in cfg.list_servers() if s.get("sync_mode") == "hub"), None
    )
    if not hub_cfg:
        return HTMLResponse(
            "<p class='text-red-400 text-sm col-span-full py-4'>No hub server configured.</p>",
            status_code=400,
        )

    spoke_cfgs = [s for s in cfg.list_servers() if s.get("sync_mode") != "hub"]

    loop = asyncio.get_running_loop()
    # Refresh hub once, then sync all spokes against fresh cache
    hub_records = await loop.run_in_executor(
        None, sync_engine.refresh_hub_cache, db_path, hub_cfg, secrets
    )
    if hub_records is not None:
        await loop.run_in_executor(
            None, sync_engine.sync_all_enabled_spokes, db_path, hub_cfg, spoke_cfgs, secrets
        )

    # Re-fetch all spokes (including disabled) with updated last_sync
    _, all_spokes = _split_servers(request)

    # Render each spoke card and concatenate
    html_parts = []
    card_tpl = templates.get_template("partials/server_card.html")
    for server in all_spokes:
        html_parts.append(card_tpl.render(server=server, request=request))

    if not html_parts:
        return HTMLResponse(
            "<p class='text-gray-500 text-sm col-span-full py-4'>No spokes configured.</p>"
        )

    return HTMLResponse("".join(html_parts))


@app.post("/api/hub/refresh", response_class=HTMLResponse)
async def hub_refresh(request: Request):
    if (redir := auth.login_required(request)):
        return redir

    cfg = request.app.state.config
    secrets = request.app.state.secrets
    db_path = request.app.state.db_path

    hub_cfg = next(
        (s for s in cfg.list_servers() if s.get("sync_mode") == "hub"), None
    )
    if not hub_cfg:
        return HTMLResponse(
            "<p class='text-red-400 text-sm'>No hub server configured.</p>",
            status_code=400,
        )

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, sync_engine.refresh_hub_cache, db_path, hub_cfg, secrets
    )

    hub_cfg = dict(hub_cfg)
    hub_cfg["last_sync"] = db.get_last_sync(db_path, hub_cfg["name"])
    hub_cfg["cache_last_updated"] = db.get_cache_last_updated(db_path, hub_cfg["name"])
    hub_cfg["cache_record_counts"] = db.get_cache_record_counts(db_path, hub_cfg["name"])
    return templates.TemplateResponse(
        "partials/server_card.html",
        {"request": request, "server": hub_cfg},
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
        {"request": request, "server": server},
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
        {"request": request, "server": server},
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

def _settings_context(db_path: str, next_sync_at: Optional[str]) -> dict:
    settings = _load_settings(db_path)
    return {
        "interval_minutes": settings.get("interval_minutes", 30),
        "enabled": settings.get("enabled", True),
        "next_sync_at": next_sync_at,
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
    try:
        interval = max(1, min(1440, int(form.get("interval_minutes", 30))))
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
