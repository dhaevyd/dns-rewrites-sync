"""Shared test fixtures"""
import pytest


class MockSecretsManager:
    """In-memory SecretsManager for testing — no file I/O required."""

    def __init__(self, credentials=None):
        self._store = credentials or {}
        self.cipher = True  # truthy sentinel so guards pass

    def load_master_key(self, password=None):
        return True

    def get_credential(self, server_name, field):
        return self._store.get(f"{server_name}_{field}")

    def set_credential(self, server_name, field, value):
        self._store[f"{server_name}_{field}"] = value

    def remove_credential(self, server_name, field):
        self._store.pop(f"{server_name}_{field}", None)


def make_config(server_type, name="test-server", url="http://localhost", **kwargs):
    """Build a minimal server config dict."""
    cfg = {
        "name": name,
        "type": server_type,
        "url": url,
        "auth": {},
        "sync_mode": "spoke",
        "enabled": True,
    }
    cfg.update(kwargs)
    return cfg


@pytest.fixture
def mock_secrets():
    return MockSecretsManager()
