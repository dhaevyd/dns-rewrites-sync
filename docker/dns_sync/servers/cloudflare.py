"""Cloudflare DNS API implementation"""

from typing import Dict, Set
import requests
from .base import DNSServer, DNSRecord

class CloudflareServer(DNSServer):
    """Cloudflare DNS over API"""
    
    def __init__(self, name: str, config: dict, secrets):
        super().__init__(name, config, secrets)
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.zone_id = self.credentials['zone_id']
        self.headers = {
            "Authorization": f"Bearer {self.credentials['api_token']}",
            "Content-Type": "application/json"
        }
    
    def connect(self) -> bool:
        """Test API token"""
        try:
            url = f"{self.base_url}/user/tokens/verify"
            resp = self.session.get(url, headers=self.headers)
            return resp.status_code == 200 and resp.json().get('success', False)
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Cloudflare: {e}")
    
    def get_records(self) -> Dict[str, Set[str]]:
        """Get all DNS records from zone"""
        url = f"{self.base_url}/zones/{self.zone_id}/dns_records"
        params = {"per_page": 5000}
        
        a_records = set()
        cname_records = set()
        page = 1
        
        while True:
            params['page'] = page
            resp = self.session.get(url, headers=self.headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            
            if not data.get('success', False):
                break
            
            for record in data.get('result', []):
                if record['type'] == 'A':
                    a_records.add(f"{record['content']} {record['name'].rstrip('.')}")
                elif record['type'] == 'CNAME':
                    cname_records.add(f"{record['name'].rstrip('.')} -> {record['content'].rstrip('.')}")
            
            if page >= data.get('result_info', {}).get('total_pages', 1):
                break
            page += 1
        
        return {'A': a_records, 'CNAME': cname_records}
    
    def add_record(self, record: DNSRecord) -> bool:
        """Add a DNS record"""
        url = f"{self.base_url}/zones/{self.zone_id}/dns_records"
        
        payload = {
            "type": record.type,
            "name": record.domain,
            "content": record.value,
            "ttl": record.ttl or 1,
            "proxied": False
        }
        
        resp = self.session.post(url, headers=self.headers, json=payload)
        return resp.status_code == 200 and resp.json().get('success', False)
    
    def delete_record(self, record: DNSRecord) -> bool:
        """Delete a DNS record (need to find by name/content first)"""
        # First, find the record ID
        url = f"{self.base_url}/zones/{self.zone_id}/dns_records"
        params = {
            "type": record.type,
            "name": record.domain,
            "content": record.value
        }
        
        resp = self.session.get(url, headers=self.headers, params=params)
        if resp.status_code != 200:
            return False
        
        data = resp.json()
        if not data.get('success', False) or not data.get('result'):
            return False
        
        # Delete by ID
        record_id = data['result'][0]['id']
        delete_url = f"{self.base_url}/zones/{self.zone_id}/dns_records/{record_id}"
        del_resp = self.session.delete(delete_url, headers=self.headers)
        
        return del_resp.status_code == 200 and del_resp.json().get('success', False)