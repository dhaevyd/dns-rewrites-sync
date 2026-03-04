"""Credential lookup from environment variables"""

import os


class SecretsManager:
    """Retrieves credentials from environment variables.

    Format: DNS_SYNC_{SERVER_NAME}_{FIELD}  (hyphens/spaces → underscores, uppercased)
    Example: server "pihole-hub", field "password" → DNS_SYNC_PIHOLE_HUB_PASSWORD
    """

    def __init__(self, config_dir="/etc/dns-sync"):
        self.config_dir = config_dir
        self.secrets_dir = os.path.join(config_dir, "secrets")

    def get_credential(self, server_name, field):
        """Return credential value from env var, or None if not set."""
        env_key = f"DNS_SYNC_{server_name.upper().replace('-', '_').replace(' ', '_')}_{field.upper()}"
        return os.environ.get(env_key)
