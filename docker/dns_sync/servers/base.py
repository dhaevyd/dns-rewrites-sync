"""Base server class with common functionality"""

from abc import ABC, abstractmethod
import requests
import time
import logging
from typing import Dict, Set, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class DNSRecord:
    """Universal DNS record format"""
    domain: str
    value: str
    type: str  # 'A' or 'CNAME'
    ttl: Optional[int] = None
    
    def to_a_format(self) -> str:
        return f"{self.value} {self.domain}"
    
    def to_cname_format(self) -> str:
        return f"{self.domain} -> {self.value}"
    
    @classmethod
    def from_a_string(cls, record_str: str) -> 'DNSRecord':
        ip, domain = record_str.split(' ', 1)
        return cls(domain=domain, value=ip, type='A')
    
    @classmethod
    def from_cname_string(cls, record_str: str) -> 'DNSRecord':
        domain, target = record_str.split(' -> ', 1)
        return cls(domain=domain, value=target, type='CNAME')

class DNSServer(ABC):
    """Enhanced base class for all DNS servers"""
    
    def __init__(self, name: str, config: dict, secrets):
        self.name = name
        self.config = config
        self.secrets = secrets
        self.session = requests.Session()
        self.headers = {}
        self.timeout = config.get('timeout', 10)
        self.retries = config.get('retries', 3)
        self._load_credentials()
    
    def _load_credentials(self):
        """Load credentials from secrets manager.

        Priority per field:
          1. Env var  DNS_SYNC_{SERVER}_{FIELD}
          2. Encrypted .enc file (legacy: value starts with 'encrypted:')
          3. Plaintext value in config.yaml auth section
        """
        self.credentials = {}
        auth_config = self.config.get('auth', {}) or {}

        for field in auth_config:
            value = auth_config[field]
            if isinstance(value, str) and value.startswith('encrypted:'):
                # Legacy CLI path: value is a reference, field name is embedded
                clean_field = value.replace('encrypted:', '')
                cred_value = self.secrets.get_credential(self.name, clean_field)
                if cred_value:
                    self.credentials[clean_field] = cred_value
            else:
                # Docker-native path: check env var / .enc first, fall back to config value
                cred_value = self.secrets.get_credential(self.name, field)
                self.credentials[field] = cred_value if cred_value else value
    
    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make request with retry logic"""
        for attempt in range(self.retries):
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                if attempt == self.retries - 1:
                    raise
                wait = (attempt + 1) * 2
                logger.debug(f"Request failed, retrying in {wait}s: {e}")
                time.sleep(wait)
    
    @abstractmethod
    def connect(self) -> bool:
        """Establish connection/session with server"""
        pass
    
    @abstractmethod
    def get_records(self) -> Dict[str, Set[str]]:
        """Get all records: {'A': set(), 'CNAME': set()}"""
        pass
    
    @abstractmethod
    def add_record(self, record: DNSRecord) -> bool:
        """Add a single record"""
        pass
    
    @abstractmethod
    def delete_record(self, record: DNSRecord) -> bool:
        """Delete a single record"""
        pass
    
    def disconnect(self) -> None:
        """Gracefully close the session. Override in subclasses that maintain server-side sessions."""
        pass

    def test_connection(self) -> bool:
        """Test if server is reachable and credentials work"""
        try:
            return self.connect()
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    def sync_records(self, target_server: 'DNSServer', dry_run: bool = False) -> Dict[str, int]:
        """Sync records from this server to target server"""
        stats = {'added': 0, 'removed': 0, 'conflicts': 0}
        
        # Get records from both servers
        source_records = self.get_records()
        target_records = target_server.get_records()
        
        for record_type in ['A', 'CNAME']:
            source_set = source_records.get(record_type, set())
            target_set = target_records.get(record_type, set())
            
            # Records to add (in source but not in target)
            to_add = source_set - target_set
            
            # Records to remove (in target but not in source)
            to_remove = target_set - source_set
            
            if dry_run:
                stats['added'] += len(to_add)
                stats['removed'] += len(to_remove)
                continue
            
            # Add new records
            for record_str in to_add:
                record = DNSRecord.from_a_string(record_str) if record_type == 'A' else DNSRecord.from_cname_string(record_str)
                try:
                    if target_server.add_record(record):
                        stats['added'] += 1
                except Exception as e:
                    logger.error(f"Failed to add {record_str}: {e}")
                    stats['conflicts'] += 1

            # Remove old records
            for record_str in to_remove:
                record = DNSRecord.from_a_string(record_str) if record_type == 'A' else DNSRecord.from_cname_string(record_str)
                try:
                    if target_server.delete_record(record):
                        stats['removed'] += 1
                except Exception as e:
                    logger.error(f"Failed to remove {record_str}: {e}")
                    stats['conflicts'] += 1
        
        return stats