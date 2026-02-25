"""Unbound DNS server implementation"""

from typing import Dict, Set
import requests
import xml.etree.ElementTree as ET
from .base import DNSServer, DNSRecord

class UnboundServer(DNSServer):
    """Unbound recursive DNS server"""
    
    def connect(self) -> bool:
        """Test Unbound control API"""
        try:
            # Unbound usually uses a local control socket or API key
            if 'api_key' in self.credentials:
                # Remote API with key
                url = f"{self.config['url']}/stats"
                headers = {"X-API-Key": self.credentials['api_key']}
                resp = self.session.get(url, headers=headers, timeout=self.timeout)
                return resp.status_code == 200
            else:
                # Local socket
                return False  # Implement local socket check
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Unbound: {e}")
    
    def get_records(self) -> Dict[str, Set[str]]:
        """Get local-data entries"""
        # This is simplified - Unbound may need config file parsing
        url = f"{self.config['url']}/local-data"
        headers = {"X-API-Key": self.credentials.get('api_key', '')}
        
        try:
            resp = self.session.get(url, headers=headers)
            resp.raise_for_status()
            
            a_records = set()
            cname_records = set()
            
            # Parse response (format depends on Unbound API)
            for line in resp.text.split('\n'):
                if ' IN A ' in line:
                    parts = line.split()
                    domain = parts[0].rstrip('.')
                    ip = parts[-1]
                    a_records.add(f"{ip} {domain}")
                elif ' IN CNAME ' in line:
                    parts = line.split()
                    domain = parts[0].rstrip('.')
                    target = parts[-1].rstrip('.')
                    cname_records.add(f"{domain} -> {target}")
            
            return {'A': a_records, 'CNAME': cname_records}
        except:
            return {'A': set(), 'CNAME': set()}
    
    def add_record(self, record: DNSRecord) -> bool:
        """Add local-data entry"""
        url = f"{self.config['url']}/local-data"
        headers = {"X-API-Key": self.credentials.get('api_key', '')}
        
        if record.type == 'A':
            data = f"{record.domain}. IN A {record.value}"
        else:
            data = f"{record.domain}. IN CNAME {record.value}."
        
        payload = {"data": data}
        resp = self.session.post(url, headers=headers, json=payload)
        return resp.status_code == 200
    
    def delete_record(self, record: DNSRecord) -> bool:
        """Delete local-data entry"""
        url = f"{self.config['url']}/local-data"
        headers = {"X-API-Key": self.credentials.get('api_key', '')}
        
        if record.type == 'A':
            data = f"{record.domain}. IN A {record.value}"
        else:
            data = f"{record.domain}. IN CNAME {record.value}."
        
        payload = {"data": data}
        resp = self.session.delete(url, headers=headers, json=payload)
        return resp.status_code == 200