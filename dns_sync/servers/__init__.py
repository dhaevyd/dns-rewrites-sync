"""Server implementations package"""

from .pihole import PiHoleServer
from .adguard import AdGuardServer
from .cloudflare import CloudflareServer
from .opnsense import OPNsenseServer
from .unbound import UnboundServer
from .generic import GenericServer

__all__ = [
    'PiHoleServer',
    'AdGuardServer', 
    'CloudflareServer',
    'OPNsenseServer',
    'UnboundServer',
    'GenericServer'
]

def create_server(server_type: str, name: str, config: dict, secrets):
    """Factory function to create appropriate server instance"""
    servers = {
        'pihole': PiHoleServer,
        'adguard': AdGuardServer,
        'cloudflare': CloudflareServer,
        'opnsense': OPNsenseServer,
        'unbound': UnboundServer,
        'generic': GenericServer
    }
    
    server_class = servers.get(server_type)
    if not server_class:
        raise ValueError(f"Unknown server type: {server_type}")
    
    return server_class(name, config, secrets)