# dns_sync/servers/technitium.py
from typing import Dict, Set
import requests
from .base import DNSServer, DNSRecord

class TechnitiumServer(DNSServer):
    """Technitium DNS Server implementation"""

    def __init__(self, name: str, config: dict, secrets):
        super().__init__(name, config, secrets)
        # Default port for Technitium admin API is 5380
        self.base_url = config.get('url', '').rstrip('/')
        self.api_token = self.credentials.get('api_token')

    def connect(self) -> bool:
        """Test connection using a simple API call (e.g., get stats)"""
        try:
            url = f"{self.base_url}/api/stats"
            params = {'token': self.api_token}
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                raise ConnectionError(f"Technitium API returned {resp.status_code}")
            return True
        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Technitium DNS: {e}")

    def get_records(self) -> Dict[str, Set[str]]:
        """
        Fetch all DNS records.
        Note: Technitium organizes records by zones. This is a simplified
        version that might list all zones and then all records within them.
        A more robust implementation would need to iterate through zones.
        """
        a_records = set()
        cname_records = set()
        params = {'token': self.api_token}

        # 1. Get list of zones
        zones_url = f"{self.base_url}/api/zones/list"
        zones_resp = self.session.get(zones_url, params=params, timeout=self.timeout)
        zones_resp.raise_for_status()
        zones_data = zones_resp.json()

        # 2. For each zone, get its records
        for zone in zones_data.get('response', {}).get('zones', []):
            zone_name = zone['zoneName']
            records_url = f"{self.base_url}/api/zone/records"
            record_params = {'token': self.api_token, 'zone': zone_name}
            records_resp = self.session.get(records_url, params=record_params, timeout=self.timeout)
            records_resp.raise_for_status()
            zone_data = records_resp.json()

            for record in zone_data.get('response', {}).get('records', []):
                record_type = record['type']
                # Handle different record types
                if record_type == 'A':
                    # Format: "IP domain"
                    a_records.add(f"{record['rData']['ipAddress']} {record['name']}")
                elif record_type == 'CNAME':
                    # Format: "domain -> target"
                    cname_records.add(f"{record['name']} -> {record['rData']['cname']}")
                # Add logic for other record types (AAAA, TXT) as needed

        return {'A': a_records, 'CNAME': cname_records}

    def add_record(self, record: DNSRecord) -> bool:
        """Add a record using the API."""
        # This requires knowing which zone the domain belongs to.
        # A simple approach is to assume the record's domain is the zone name.
        # A more robust approach would query the zone list first.
        params = {'token': self.api_token}
        data = {
            'zone': self._extract_zone(record.domain),
            'domain': record.domain,
            'type': record.type,
        }
        if record.type == 'A':
            data['ipAddress'] = record.value
        elif record.type == 'CNAME':
            data['cname'] = record.value

        url = f"{self.base_url}/api/zone/record/add"
        resp = self.session.post(url, params=params, data=data)
        return resp.status_code == 200

    def delete_record(self, record: DNSRecord) -> bool:
        """Delete a record using POST /api/zone/record/delete."""
        params = {'token': self.api_token}
        data = {
            'zone': self._extract_zone(record.domain),
            'domain': record.domain,
            'type': record.type,
        }
        if record.type == 'A':
            data['ipAddress'] = record.value
        elif record.type == 'CNAME':
            data['cname'] = record.value

        url = f"{self.base_url}/api/zone/record/delete"
        resp = self.session.post(url, params=params, data=data)
        return resp.status_code == 200

    def _extract_zone(self, domain: str) -> str:
        """Helper to extract the zone name from a domain."""
        parts = domain.split('.')
        if len(parts) > 1:
            return '.'.join(parts[1:]) + '.'
        return domain + '.'