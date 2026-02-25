"""Configuration management"""

import os
import yaml
from .registry import SERVER_TYPES

class ConfigManager:
    """Manages server configuration"""
    
    def __init__(self, config_dir="/etc/dns-sync"):
        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, "config.yaml")
        self.config = self._load_or_create()
    
    def _load_or_create(self):
        """Load existing config or create empty one"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f) or {'servers': []}
        return {'servers': []}
    
    def _save(self):
        """Save config to file"""
        with open(self.config_file, 'w') as f:
            yaml.dump(self.config, f, default_flow_style=False)
        os.chmod(self.config_file, 0o660)
    
    def add_server(self, server_data):
        """Add a new server configuration"""
        # Remove any existing server with same name
        self.config['servers'] = [
            s for s in self.config['servers'] 
            if s['name'] != server_data['name']
        ]
        
        self.config['servers'].append(server_data)
        self._save()
        return True
    
    def get_server(self, name):
        """Get server by name"""
        for server in self.config['servers']:
            if server['name'] == name:
                return server
        return None
    
    def list_servers(self):
        """List all configured servers"""
        return self.config['servers']
    
    def remove_server(self, name):
        """Remove a server configuration"""
        self.config['servers'] = [
            s for s in self.config['servers'] 
            if s['name'] != name
        ]
        self._save()
        return True
    
    def update_server(self, name, updates):
        """Update server configuration"""
        for i, server in enumerate(self.config['servers']):
            if server['name'] == name:
                self.config['servers'][i].update(updates)
                self._save()
                return True
        return False