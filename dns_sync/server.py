"""Base server class"""

from abc import ABC, abstractmethod
import requests

class DNSServer(ABC):
    """Base class for all DNS servers"""
    
    def __init__(self, config, secrets):
        self.name = config['name']
        self.config = config
        self.secrets = secrets
        self._load_credentials()
    
    def _load_credentials(self):
        """Load credentials from secrets manager"""
        self.credentials = {}
        for field in self.config.get('auth', {}):
            clean_field = field.replace('encrypted:', '')
            value = self.secrets.get_credential(self.name, clean_field)
            if value:
                self.credentials[clean_field] = value
    
    @abstractmethod
    def test_connection(self):
        """Test if server is reachable and credentials work"""
        pass
    
    @abstractmethod
    def get_records(self):
        """Get all records from server"""
        pass
    
    @abstractmethod
    def add_record(self, record_type, domain, value):
        """Add a record"""
        pass
    
    @abstractmethod
    def delete_record(self, record_type, domain, value):
        """Delete a record"""
        pass

def create_server(config, secrets):
    """Factory function to create appropriate server instance"""
    server_type = config['type']
    
    if server_type == 'pihole':
        from .servers.pihole import PiHoleServer
        return PiHoleServer(config, secrets)
    elif server_type == 'adguard':
        from .servers.adguard import AdGuardServer
        return AdGuardServer(config, secrets)
    elif server_type == 'cloudflare':
        from .servers.cloudflare import CloudflareServer
        return CloudflareServer(config, secrets)
    elif server_type == 'opnsense':
        from .servers.opnsense import OPNsenseServer
        return OPNsenseServer(config, secrets)
    elif server_type == 'unbound':
        from .servers.unbound import UnboundServer
        return UnboundServer(config, secrets)
    else:
        from .servers.generic import GenericServer
        return GenericServer(config, secrets)