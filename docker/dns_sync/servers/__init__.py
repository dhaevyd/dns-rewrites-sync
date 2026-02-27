"""Server implementations package"""

import importlib
from ..registry import SERVER_TYPES

__all__ = ['create_server']


def create_server(server_type: str, name: str, config: dict, secrets):
    """Registry-driven factory. New server types only need an entry in registry.py."""
    server_info = SERVER_TYPES.get(server_type)
    if not server_info:
        raise ValueError(f"Unknown server type: {server_type!r}")
    module = importlib.import_module(server_info['module'])
    cls = getattr(module, server_info['class'])
    return cls(name, config, secrets)
