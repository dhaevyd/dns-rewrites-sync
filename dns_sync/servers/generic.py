"""Generic DNS API implementation - configurable for any API"""

from typing import Dict, Set, Optional
import requests
import json
from .base import DNSServer, DNSRecord

class GenericServer(DNSServer):
    """Generic DNS server with configurable API endpoints"""
    
    def __init__(self, name: str, config: dict, secrets):
        super().__init__(name, config, secrets)
        self.api_config = config.get('api_config', {})
        self._setup_auth()
    
    def _setup_auth(self):
        """Setup authentication based on config"""
        auth_type = self.api_config.get('auth_type', 'none')
        
        if auth_type == 'basic':
            self.session.auth = (
                self.credentials.get('username', ''),
                self.credentials.get('password', '')
            )
        elif auth_type == 'token':
            token = self.credentials.get('api_token', '')
            token_header = self.api_config.get('token_header', 'Authorization')
            token_format = self.api_config.get('token_format', 'Bearer {}')
            self.headers[token_header] = token_format.format(token)
        elif auth_type == 'header':
            for header in self.api_config.get('headers', []):
                name = header['name']
                value = self.credentials.get(header['value_from'], '')
                self.headers[name] = value
    
    def connect(self) -> bool:
        """Test connection using test endpoint"""
        test_config = self.api_config.get('test', {})
        if not test_config:
            return True  # Assume working if no test configured
        
        method = test_config.get('method', 'GET')
        url = f"{self.config['url']}{test_config.get('path', '')}"
        
        try:
            resp = self.session.request(
                method,
                url,
                headers=self.headers,
                timeout=self.timeout
            )
            
            # Check response using configured validation
            expected = test_config.get('expected', {})
            if expected.get('status'):
                return resp.status_code == expected['status']
            
            return resp.status_code < 400
        except:
            return False
    
    def get_records(self) -> Dict[str, Set[str]]:
        """Get records using configured endpoints"""
        records_config = self.api_config.get('get_records', {})
        a_records = set()
        cname_records = set()
        
        for record_type in ['A', 'CNAME']:
            type_config = records_config.get(record_type)
            if not type_config:
                continue
            
            method = type_config.get('method', 'GET')
            url = f"{self.config['url']}{type_config.get('path', '')}"
            
            resp = self.session.request(
                method,
                url,
                headers=self.headers,
                json=type_config.get('body')
            )
            
            if resp.status_code != 200:
                continue
            
            # Parse response using configured paths
            data = resp.json()
            for path in type_config.get('record_path', []):
                data = data.get(path, {})
            
            if isinstance(data, list):
                for item in data:
                    domain = self._extract_value(item, type_config.get('domain_field', 'domain'))
                    value = self._extract_value(item, type_config.get('value_field', 'value'))
                    
                    if domain and value:
                        if record_type == 'A':
                            a_records.add(f"{value} {domain}")
                        else:
                            cname_records.add(f"{domain} -> {value}")
        
        return {'A': a_records, 'CNAME': cname_records}
    
    def add_record(self, record: DNSRecord) -> bool:
        """Add record using configured endpoint"""
        add_config = self.api_config.get('add_record', {}).get(record.type)
        if not add_config:
            return False
        
        # Build payload using template
        payload = {}
        for field, template in add_config.get('payload_template', {}).items():
            payload[field] = template.replace('{domain}', record.domain).replace('{value}', record.value)
        
        method = add_config.get('method', 'POST')
        url = f"{self.config['url']}{add_config.get('path', '')}"
        
        resp = self.session.request(
            method,
            url,
            headers=self.headers,
            json=payload
        )
        
        expected = add_config.get('expected', {})
        if expected.get('status'):
            return resp.status_code == expected['status']
        
        return resp.status_code in [200, 201, 204]
    
    def delete_record(self, record: DNSRecord) -> bool:
        """Delete record using configured endpoint"""
        delete_config = self.api_config.get('delete_record', {}).get(record.type)
        if not delete_config:
            return False
        
        # Build payload using template
        payload = {}
        for field, template in delete_config.get('payload_template', {}).items():
            payload[field] = template.replace('{domain}', record.domain).replace('{value}', record.value)
        
        method = delete_config.get('method', 'DELETE')
        url = f"{self.config['url']}{delete_config.get('path', '')}"
        
        resp = self.session.request(
            method,
            url,
            headers=self.headers,
            json=payload if method in ['POST', 'PUT'] else None
        )
        
        expected = delete_config.get('expected', {})
        if expected.get('status'):
            return resp.status_code == expected['status']
        
        return resp.status_code in [200, 202, 204]
    
    def _extract_value(self, data: dict, path: str) -> Optional[str]:
        """Extract value from nested dict using dot notation"""
        if not path:
            return None
        
        parts = path.split('.')
        current = data
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return str(current) if current else None