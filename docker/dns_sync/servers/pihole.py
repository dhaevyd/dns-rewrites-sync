"""Pi-hole v6+ server implementation"""

import logging
from typing import Dict, Set, Optional
import requests
import urllib.parse
from .base import DNSServer, DNSRecord

logger = logging.getLogger(__name__)

# Module-level session cache: {base_url: {"sid": ..., "csrf": ...}}
# Persists across sync cycles so we don't re-authenticate every time.
_session_cache: dict = {}


class PiHoleServer(DNSServer):
    """Pi-hole v6+ DNS server"""

    UA = "dns-rewrites-sync"

    def __init__(self, name: str, config: dict, secrets):
        super().__init__(name, config, secrets)
        self.sid = None
        self.csrf = None
        self.base_url = self.config['url']
        self.session.headers.update({"User-Agent": self.UA})

    def connect(self) -> bool:
        """Reuse cached session if still valid, otherwise authenticate fresh."""
        # Try cached session first
        cached = _session_cache.get(self.base_url)
        if cached and self._test_session(cached["sid"]):
            self._apply_session(cached["sid"], cached.get("csrf"))
            logger.debug("Reusing cached Pi-hole session for %s", self.name)
            return True

        # Cached session gone or expired — authenticate fresh
        if cached:
            del _session_cache[self.base_url]

        url = f"{self.base_url}/api/auth"
        try:
            resp = self.session.post(
                url,
                json={"password": self.credentials['password']},
                timeout=self.timeout
            )
            if resp.status_code == 429:
                raise ConnectionError("Pi-hole rate limit hit — wait a moment and try again")
            resp.raise_for_status()
            data = resp.json()

            sid = data['session']['sid']
            csrf = data['session'].get('csrf')
            self._apply_session(sid, csrf)
            _session_cache[self.base_url] = {"sid": sid, "csrf": csrf}
            self._cleanup_orphaned_sessions()
            return True
        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Pi-hole: {e}")

    def _test_session(self, sid: str) -> bool:
        """Return True if the session is still valid on the server."""
        try:
            resp = self.session.get(
                f"{self.base_url}/api/auth",
                headers={"X-FTL-SID": sid, "Content-Type": "application/json"},
                timeout=self.timeout
            )
            return resp.status_code == 200 and resp.json().get("session", {}).get("valid", False)
        except Exception:
            return False

    def _apply_session(self, sid: str, csrf: Optional[str]) -> None:
        self.sid = sid
        self.csrf = csrf
        self.headers = {"X-FTL-SID": self.sid, "Content-Type": "application/json"}
        if self.csrf:
            self.headers["X-CSRF-TOKEN"] = self.csrf

    def _cleanup_orphaned_sessions(self) -> None:
        """Delete any active sessions created by this app (matched by User-Agent) except the current one."""
        try:
            url = f"{self.base_url}/api/auth/sessions"
            resp = self.session.get(url, headers=self.headers, timeout=self.timeout)
            if resp.status_code != 200:
                return
            sessions = resp.json().get("sessions", [])
            for s in sessions:
                if s.get("user_agent", "") == self.UA and s.get("sid") != self.sid:
                    del_url = f"{self.base_url}/api/auth/sessions/{s['id']}"
                    self.session.delete(del_url, headers=self.headers, timeout=self.timeout)
                    logger.debug("Cleaned up orphaned Pi-hole session %s", s.get("id"))
        except Exception as e:
            logger.debug("Session cleanup skipped (%s): %s", self.name, e)

    def get_records(self) -> Dict[str, Set[str]]:
        """Get all A and CNAME records"""
        if not self.sid:
            self.connect()

        url = f"{self.base_url}/api/config"
        resp = self.session.get(url, headers=self.headers, timeout=self.timeout)
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
            encoded = urllib.parse.quote(f"{record.value} {record.domain}", safe='')
            url = f"{self.base_url}/api/config/dns/hosts/{encoded}"
        else:  # CNAME
            encoded = f"{record.domain},{record.value}"
            url = f"{self.base_url}/api/config/dns/cnameRecords/{encoded}"

        resp = self.session.put(url, headers=self.headers, timeout=self.timeout)
        if resp.status_code in [200, 201, 204]:
            return True
        logger.warning(
            "Pi-hole add_record HTTP %s for %s %s %s — body: %s",
            resp.status_code, record.type, record.domain, record.value, resp.text[:200],
        )
        return False

    def delete_record(self, record: DNSRecord) -> bool:
        """Delete a record from Pi-hole"""
        if not self.sid:
            self.connect()

        if record.type == 'A':
            encoded = urllib.parse.quote(f"{record.value} {record.domain}", safe='')
            url = f"{self.base_url}/api/config/dns/hosts/{encoded}"
        else:  # CNAME
            encoded = f"{record.domain},{record.value}"
            url = f"{self.base_url}/api/config/dns/cnameRecords/{encoded}"

        resp = self.session.delete(url, headers=self.headers, timeout=self.timeout)
        if resp.status_code in [200, 204]:
            return True
        logger.warning(
            "Pi-hole delete_record HTTP %s for %s %s %s — body: %s",
            resp.status_code, record.type, record.domain, record.value, resp.text[:200],
        )
        return False

    def disconnect(self) -> None:
        """Release instance state but keep session cached for reuse next cycle."""
        self.sid = None
        self.csrf = None
        self.headers = {}
