"""OPNsense/pfSense server implementation"""

from typing import Dict, Set
import requests
import hashlib
import time
from .base import DNSServer, DNSRecord

class OPNsenseServer(DNSServer):
    """OPNsense/pfSense router DNS"""
    
    def __init__(self, name: str, config: dict, secrets):
        super().__init__(name, config, secrets)
        self.api_key = self.credentials['api_key']
        self.api_secret = self.credentials['api_secret']
        self._setup_auth()
    
    def _setup_auth(self):
        """Setup HTTP authentication"""
        self.session.auth = (self.api_key, self.api_secret)
    
    def connect(self) -> bool:
        """Test API connection"""
        try:
            url = f"{self.config['url']}/api/core/firmware/info"
            resp = self.session.get(url, timeout=self.timeout)
            return resp.status_code == 200
        except Exception as e:
            raise ConnectionError(f"Failed to connect to OPNsense: {e}")
    
    def get_records(self) -> Dict[str, Set[str]]:
        """Get host overrides (A records)"""
        # OPNsense typically only does A records via API
        url = f"{self.config['url']}/api/unbound/settings/get"
        
        resp = self.session.get(url)
        resp.raise_for_status()
        data = resp.json()
        
        a_records = set()
        
        # Parse host overrides
        hosts = data.get('hosts', {}).get('host', [])
        for host in hosts:
            if isinstance(host, dict):
                domain = host.get('hostname', '')
                if domain and host.get('domain', ''):
                    fqdn = f"{domain}.{host['domain']}".rstrip('.')
                    ip = host.get('rr', {}).get('a', '')
                    if ip:
                        a_records.add(f"{ip} {fqdn}")
        
        return {'A': a_records, 'CNAME': set()}  # OPNsense may not support CNAME via API
    
    def add_record(self, record: DNSRecord) -> bool:
        """Add a host override"""
        if record.type != 'A':
            return False  # OPNsense may not support CNAME via API
        
        # Parse domain into hostname and domain
        parts = record.domain.split('.', 1)
        hostname = parts[0]
        domain = parts[1] if len(parts) > 1 else ''
        
        payload = {
            "host": {
                "enabled": "1",
                "hostname": hostname,
                "domain": domain,
                "rr": {
                    "a": record.value
                }
            }
        }
        
        url = f"{self.config['url']}/api/unbound/settings/addHost"
        resp = self.session.post(url, json=payload)
        return resp.status_code == 200
    
    def delete_record(self, record: DNSRecord) -> bool:
        """Delete a host override"""
        if record.type != 'A':
            return False
        
        # Need to find the UUID first
        parts = record.domain.split('.', 1)
        hostname = parts[0]
        domain = parts[1] if len(parts) > 1 else ''
        
        # Get all hosts to find UUID
        list_url = f"{self.config['url']}/api/unbound/settings/searchHost"
        resp = self.session.get(list_url)
        if resp.status_code != 200:
            return False
        
        data = resp.json()
        for item in data.get('rows', []):
            if item.get('hostname') == hostname and item.get('domain') == domain:
                uuid = item.get('uuid')
                if uuid:
                    del_url = f"{self.config['url']}/api/unbound/settings/delHost/{uuid}"
                    del_resp = self.session.post(del_url)
                    return del_resp.status_code == 200
        
        return False