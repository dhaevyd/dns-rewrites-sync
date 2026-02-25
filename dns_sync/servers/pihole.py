"""Pi-hole v6+ server implementation"""

from typing import Dict, Set
import requests
import urllib.parse
from .base import DNSServer, DNSRecord

class PiHoleServer(DNSServer):
    """Pi-hole v6+ DNS server"""
    
    def __init__(self, name: str, config: dict, secrets):
        super().__init__(name, config, secrets)
        self.sid = None
        self.csrf = None
    
    def connect(self) -> bool:
        """Authenticate to Pi-hole and get session"""
        url = f"{self.config['url']}/api/auth"
        
        try:
            resp = self.session.post(
                url,
                json={"password": self.credentials['password']},
                timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            
            self.sid = data['session']['sid']
            self.csrf = data['session']['csrf']
            self.headers = {
                "X-FTL-SID": self.sid,
                "X-CSRF-TOKEN": self.csrf,
                "Content-Type": "application/json"
            }
            return True
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Pi-hole: {e}")
    
    def get_records(self) -> Dict[str, Set[str]]:
        """Get all A and CNAME records"""
        if not self.sid:
            self.connect()
        
        url = f"{self.config['url']}/api/config"
        resp = self.session.get(url, headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        
        hosts = data.get('config', {}).get('dns', {}).get('hosts', [])
        cnames = data.get('config', {}).get('dns', {}).get('cnameRecords', [])
        
        a_records = set()
        for host in hosts:
            if ' ' in host:
                a_records.add(host)
        
        cname_records = set()
        for cname in cnames:
            if ',' in cname:
                domain, target = cname.split(',')[:2]
                cname_records.add(f"{domain} -> {target}")
        
        return {'A': a_records, 'CNAME': cname_records}
    
    def add_record(self, record: DNSRecord) -> bool:
        """Add a record to Pi-hole"""
        if not self.sid:
            self.connect()
        
        if record.type == 'A':
            encoded = f"{record.value}%20{record.domain}"
            url = f"{self.config['url']}/api/config/dns/hosts/{encoded}"
        else:  # CNAME
            encoded = f"{record.domain},{record.value}"
            url = f"{self.config['url']}/api/config/dns/cnameRecords/{encoded}"
        
        resp = self.session.put(url, headers=self.headers)
        return resp.status_code in [200, 204]
    
    def delete_record(self, record: DNSRecord) -> bool:
        """Delete a record from Pi-hole"""
        if not self.sid:
            self.connect()
        
        if record.type == 'A':
            encoded = f"{record.value}%20{record.domain}"
            url = f"{self.config['url']}/api/config/dns/hosts/{encoded}"
        else:  # CNAME
            encoded = f"{record.domain},{record.value}"
            url = f"{self.config['url']}/api/config/dns/cnameRecords/{encoded}"
        
        resp = self.session.delete(url, headers=self.headers)
        return resp.status_code in [200, 204]
    
    def disconnect(self):
        """Logout from Pi-hole"""
        if self.sid:
            url = f"{self.config['url']}/api/auth"
            try:
                self.session.delete(url, headers=self.headers)
            except:
                pass
            self.sid = None