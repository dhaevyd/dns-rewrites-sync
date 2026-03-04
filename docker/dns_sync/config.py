"""Configuration management"""

import os
import yaml
from .registry import SERVER_TYPES


class ConfigManager:
    """Manages server configuration. Supports two formats:

    New format (detected by top-level 'hubs:' key):
        hubs:   [{name, type, url, auth, enabled}]
        servers: [{name, type, hub: hub-name, url, auth, enabled}]  # spokes only

    Legacy format (backward compat):
        servers: [{name, type, sync_mode: hub|spoke, url, auth, enabled}]
    """

    def __init__(self, config_dir="/etc/dns-sync"):
        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, "config.yaml")
        self.config = self._load_or_create()

    def _is_new_format(self) -> bool:
        return "hubs" in self.config

    def _load_or_create(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as f:
                return yaml.safe_load(f) or {"servers": []}
        return {"servers": []}

    def _save(self):
        """Atomic write via temp file + os.replace."""
        tmp = self.config_file + ".tmp"
        with open(tmp, "w") as f:
            yaml.dump(self.config, f, default_flow_style=False)
        os.replace(tmp, self.config_file)
        os.chmod(self.config_file, 0o660)

    # ------------------------------------------------------------------
    # Multi-hub accessors
    # ------------------------------------------------------------------

    def list_hubs(self) -> list:
        """Return all hub configs (new format: hubs: key; legacy: sync_mode=hub servers)."""
        if self._is_new_format():
            return list(self.config.get("hubs", []))
        return [s for s in self.config.get("servers", []) if s.get("sync_mode") == "hub"]

    def list_spokes_for_hub(self, hub_name: str) -> list:
        """Return spokes belonging to hub_name.

        New format: servers with hub: hub_name field.
        Legacy: all non-hub servers (single hub owns everything).
        """
        if self._is_new_format():
            return [s for s in self.config.get("servers", []) if s.get("hub") == hub_name]
        return [s for s in self.config.get("servers", []) if s.get("sync_mode") != "hub"]

    # ------------------------------------------------------------------
    # Generic accessors (used by existing app.py call sites)
    # ------------------------------------------------------------------

    def list_servers(self) -> list:
        """Return all server configs.

        New format: union of hubs + servers so existing call sites
        (which filter by sync_mode or hub field) continue to work.
        Legacy: flat servers list.
        """
        if self._is_new_format():
            return list(self.config.get("hubs", [])) + list(self.config.get("servers", []))
        return list(self.config.get("servers", []))

    def get_server(self, name: str):
        """Get server by name. Searches hubs list then servers list."""
        for server in self.list_servers():
            if server["name"] == name:
                return server
        return None

    # ------------------------------------------------------------------
    # Mutations (spokes only — hubs are managed via config.yaml directly)
    # ------------------------------------------------------------------

    def add_server(self, server_data):
        """Add or replace a spoke in the servers list."""
        servers = self.config.setdefault("servers", [])
        self.config["servers"] = [s for s in servers if s["name"] != server_data["name"]]
        self.config["servers"].append(server_data)
        self._save()
        return True

    def remove_server(self, name):
        """Remove a server by name from the servers list."""
        self.config["servers"] = [
            s for s in self.config.get("servers", []) if s["name"] != name
        ]
        self._save()
        return True

    def update_server(self, name, updates):
        """Update a server config by name. Searches servers list then hubs list."""
        for i, server in enumerate(self.config.get("servers", [])):
            if server["name"] == name:
                self.config["servers"][i].update(updates)
                self._save()
                return True
        # Also support toggling hubs (e.g. enable/disable)
        for i, hub in enumerate(self.config.get("hubs", [])):
            if hub["name"] == name:
                self.config["hubs"][i].update(updates)
                self._save()
                return True
        return False
