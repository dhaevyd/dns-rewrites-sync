"""Server type registry - knows what each server needs"""

SERVER_TYPES = {
    "pihole": {
        "name": "Pi-hole v6+",
        "description": "Pi-hole DNS server (version 6 or higher)",
        "auth_fields": [
            {"name": "password", "type": "password", "prompt": "Password"}
        ],
        "supports": ["A", "CNAME"],
        "class": "PiHoleServer",
        "module": "dns_sync.servers.pihole",
        "doc_url": "https://docs.pi-hole.net/api/",
        "default_port": 80
    },
    "adguard": {
        "name": "AdGuard Home",
        "description": "AdGuard Home DNS server",
        "auth_fields": [
            {"name": "username", "type": "string", "prompt": "Username"},
            {"name": "password", "type": "password", "prompt": "Password"}
        ],
        "supports": ["A", "CNAME"],
        "class": "AdGuardServer",
        "module": "dns_sync.servers.adguard",
        "doc_url": "https://adguard.com/docs/api/",
        "default_port": 80
    },
    "cloudflare": {
        "name": "Cloudflare DNS",
        "description": "Cloudflare DNS over API",
        "auth_fields": [
            {"name": "api_token", "type": "password", "prompt": "API Token"},
            {"name": "zone_id", "type": "string", "prompt": "Zone ID"}
        ],
        "supports": ["A", "CNAME", "TXT"],
        "class": "CloudflareServer",
        "module": "dns_sync.servers.cloudflare",
        "doc_url": "https://developers.cloudflare.com/api/",
        "default_port": 443
    },
    "opnsense": {
        "name": "OPNsense/pfSense",
        "description": "OPNsense or pfSense router",
        "auth_fields": [
            {"name": "api_key", "type": "string", "prompt": "API Key"},
            {"name": "api_secret", "type": "password", "prompt": "API Secret"}
        ],
        "supports": ["A"],
        "class": "OPNsenseServer",
        "module": "dns_sync.servers.opnsense",
        "doc_url": "https://docs.opnsense.org/development/api.html",
        "default_port": 443
    },
    "unbound": {
        "name": "Unbound",
        "description": "Unbound recursive DNS server",
        "auth_fields": [
            {"name": "api_key", "type": "password", "prompt": "API Key", "optional": True}
        ],
        "supports": ["A", "CNAME"],
        "class": "UnboundServer",
        "module": "dns_sync.servers.unbound",
        "doc_url": "https://unbound.docs.nlnetlabs.com/",
        "default_port": 443
    },
    "technitium": {
        "name": "Technitium DNS",
        "description": "Self-hosted, open-source DNS server",
        "auth_fields": [
            {"name": "api_token", "type": "password", "prompt": "API Token"}
        ],
        "supports": ["A", "CNAME", "TXT", "AAAA"], # And more!
        "class": "TechnitiumServer",
        "module": "dns_sync.servers.technitium",
        "doc_url": "https://technitium.com/dns/",
        "default_port": 5380
    },
    "generic": {
        "name": "Generic DNS API",
        "description": "Custom DNS server with configurable API",
        "auth_fields": [
            {"name": "username", "type": "string", "prompt": "Username", "optional": True},
            {"name": "password", "type": "password", "prompt": "Password", "optional": True},
            {"name": "api_token", "type": "password", "prompt": "API Token", "optional": True}
        ],
        "supports": ["A", "CNAME"],
        "class": "GenericServer",
        "module": "dns_sync.servers.generic",
        "doc_url": None,
        "default_port": 80
    }
}


def get_server_types():
    """Return list of (key, name, description) tuples for CLI display."""
    return [(k, v["name"], v["description"]) for k, v in SERVER_TYPES.items()]


def get_auth_fields(server_type):
    """Return auth field definitions for a given server type."""
    return SERVER_TYPES.get(server_type, {}).get("auth_fields", [])