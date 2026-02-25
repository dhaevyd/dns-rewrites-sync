"""AdGuard Home server implementation"""

from typing import Dict, Set
import requests
import ipaddress
from .base import DNSServer, DNSRecord

class AdGuardServer(DNSServer):
    """AdGuard Home DNS server"""
    
    def connect(self) -> bool:
        """AdGuard uses basic auth, just test connection"""
        try:
            url = f"{self.config['url']}/control/status"
            resp = self.session.get(
                url,
                auth=(self.credentials['username'], self.credentials['password']),
                timeout=self.timeout
            )
            return resp.status_code == 200
        except Exception as e:
            raise ConnectionError(f"Failed to connect to AdGuard: {e}")
    
    def get_records(self) -> Dict[str, Set[str]]:
        """Get all rewrite entries"""
        url = f"{self.config['url']}/control/rewrite/list"
        resp = self.session.get(
            url,
            auth=(self.credentials['username'], self.credentials['password'])
        )
        resp.raise_for_status()
        
        a_records = set()
        cname_records = set()
        
        for item in resp.json():
            domain = item.get('domain', '').rstrip('.')
            answer = item.get('answer', '').rstrip('.')
            
            # Detect record type
            try:
                ipaddress.ip_address(answer)
                a_records.add(f"{answer} {domain}")
            except ValueError:
                cname_records.add(f"{domain} -> {answer}")
        
        return {'A': a_records, 'CNAME': cname_records}
    
    def add_record(self, record: DNSRecord) -> bool:
        """Add a rewrite entry"""
        url = f"{self.config['url']}/control/rewrite/add"
        payload = {"domain": record.domain, "answer": record.value}
        
        resp = self.session.post(
            url,
            json=payload,
            auth=(self.credentials['username'], self.credentials['password'])
        )
        return resp.status_code == 200
    
    def delete_record(self, record: DNSRecord) -> bool:
        """Delete a rewrite entry"""
        url = f"{self.config['url']}/control/rewrite/delete"
        payload = {"domain": record.domain, "answer": record.value}
        
        resp = self.session.post(
            url,
            json=payload,
            auth=(self.credentials['username'], self.credentials['password'])
        )
        return resp.status_code == 200