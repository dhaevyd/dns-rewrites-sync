"""Unit tests for all DNS server implementations and core sync logic."""
import pytest
from unittest.mock import MagicMock, patch, call
import requests

from conftest import MockSecretsManager, make_config
from dns_sync.servers.base import DNSServer, DNSRecord
from dns_sync.servers.pihole import PiHoleServer
from dns_sync.servers.adguard import AdGuardServer
from dns_sync.servers.cloudflare import CloudflareServer
from dns_sync.servers.opnsense import OPNsenseServer
from dns_sync.servers.unbound import UnboundServer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def mock_resp(status_code=200, json_data=None, text=""):
    """Build a fake requests.Response-like MagicMock."""
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data if json_data is not None else {}
    m.text = text
    m.raise_for_status.return_value = None
    return m


def _pihole(name="pihole"):
    secrets = MockSecretsManager({f"{name}_password": "secret"})
    cfg = make_config("pihole", name=name, url="http://pihole.local",
                      auth={"password": "encrypted:password"})
    return PiHoleServer(name, cfg, secrets)


def _adguard(name="adguard"):
    secrets = MockSecretsManager({f"{name}_username": "admin", f"{name}_password": "pass"})
    cfg = make_config("adguard", name=name, url="http://adguard.local",
                      auth={"username": "encrypted:username", "password": "encrypted:password"})
    return AdGuardServer(name, cfg, secrets)


def _cloudflare(name="cf"):
    secrets = MockSecretsManager({f"{name}_api_token": "tok", f"{name}_zone_id": "zone123"})
    cfg = make_config("cloudflare", name=name, url="https://api.cloudflare.com/client/v4",
                      auth={"api_token": "encrypted:api_token", "zone_id": "encrypted:zone_id"})
    return CloudflareServer(name, cfg, secrets)


def _opnsense(name="opn"):
    secrets = MockSecretsManager({f"{name}_api_key": "key", f"{name}_api_secret": "secret"})
    cfg = make_config("opnsense", name=name, url="https://opnsense.local",
                      auth={"api_key": "encrypted:api_key", "api_secret": "encrypted:api_secret"})
    return OPNsenseServer(name, cfg, secrets)


def _unbound(name="unbound"):
    secrets = MockSecretsManager({f"{name}_api_key": "ukey"})
    cfg = make_config("unbound", name=name, url="http://unbound.local",
                      auth={"api_key": "encrypted:api_key"})
    return UnboundServer(name, cfg, secrets)


# ---------------------------------------------------------------------------
# DNSRecord
# ---------------------------------------------------------------------------

class TestDNSRecord:
    def test_from_a_string(self):
        r = DNSRecord.from_a_string("1.2.3.4 example.com")
        assert r.domain == "example.com"
        assert r.value == "1.2.3.4"
        assert r.type == "A"

    def test_from_cname_string(self):
        r = DNSRecord.from_cname_string("alias.local -> target.local")
        assert r.domain == "alias.local"
        assert r.value == "target.local"
        assert r.type == "CNAME"

    def test_a_roundtrip(self):
        original = "1.2.3.4 example.com"
        assert DNSRecord.from_a_string(original).to_a_format() == original

    def test_cname_roundtrip(self):
        original = "alias.local -> target.local"
        assert DNSRecord.from_cname_string(original).to_cname_format() == original


# ---------------------------------------------------------------------------
# PiHoleServer
# ---------------------------------------------------------------------------

class TestPiHoleServer:
    def test_connect_sets_session(self):
        server = _pihole()
        server.session = MagicMock()
        server.session.post.return_value = mock_resp(200, {
            "session": {"sid": "abc", "csrf": "xyz"}
        })
        assert server.connect() is True
        assert server.sid == "abc"
        assert server.csrf == "xyz"

    def test_get_records_parses_hosts_and_cnames(self):
        server = _pihole()
        server.sid = "abc"
        server.csrf = "xyz"
        server.headers = {}
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(200, {
            "config": {
                "dns": {
                    "hosts": ["1.2.3.4 nas.home", "5.6.7.8 printer.home"],
                    "cnameRecords": ["alias.home,nas.home", "other.home,printer.home"]
                }
            }
        })
        records = server.get_records()
        assert "1.2.3.4 nas.home" in records["A"]
        assert "5.6.7.8 printer.home" in records["A"]
        assert "alias.home -> nas.home" in records["CNAME"]
        assert "other.home -> printer.home" in records["CNAME"]

    def test_add_a_record(self):
        server = _pihole()
        server.sid = "abc"
        server.headers = {}
        server.session = MagicMock()
        server.session.put.return_value = mock_resp(204)
        record = DNSRecord(domain="nas.home", value="1.2.3.4", type="A")
        assert server.add_record(record) is True
        server.session.put.assert_called_once()

    def test_delete_cname_record(self):
        server = _pihole()
        server.sid = "abc"
        server.headers = {}
        server.session = MagicMock()
        server.session.delete.return_value = mock_resp(200)
        record = DNSRecord(domain="alias.home", value="nas.home", type="CNAME")
        assert server.delete_record(record) is True
        server.session.delete.assert_called_once()


# ---------------------------------------------------------------------------
# AdGuardServer
# ---------------------------------------------------------------------------

class TestAdGuardServer:
    def test_connect_returns_true_on_200(self):
        server = _adguard()
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(200)
        assert server.connect() is True

    def test_connect_returns_false_on_401(self):
        server = _adguard()
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(401)
        assert server.connect() is False

    def test_get_records_detects_a_and_cname(self):
        server = _adguard()
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(200, [
            {"domain": "nas.home", "answer": "1.2.3.4"},
            {"domain": "alias.home", "answer": "nas.home"},
        ])
        records = server.get_records()
        assert "1.2.3.4 nas.home" in records["A"]
        assert "alias.home -> nas.home" in records["CNAME"]

    def test_add_record(self):
        server = _adguard()
        server.session = MagicMock()
        server.session.post.return_value = mock_resp(200)
        record = DNSRecord(domain="nas.home", value="1.2.3.4", type="A")
        assert server.add_record(record) is True

    def test_delete_record(self):
        server = _adguard()
        server.session = MagicMock()
        server.session.post.return_value = mock_resp(200)
        record = DNSRecord(domain="nas.home", value="1.2.3.4", type="A")
        assert server.delete_record(record) is True


# ---------------------------------------------------------------------------
# CloudflareServer
# ---------------------------------------------------------------------------

class TestCloudflareServer:
    def test_connect_success(self):
        server = _cloudflare()
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(200, {"success": True})
        assert server.connect() is True

    def test_connect_fails_when_not_success(self):
        server = _cloudflare()
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(200, {"success": False})
        assert server.connect() is False

    def test_get_records_single_page(self):
        server = _cloudflare()
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(200, {
            "success": True,
            "result": [
                {"type": "A", "name": "nas.home", "content": "1.2.3.4"},
                {"type": "CNAME", "name": "alias.home", "content": "nas.home"},
            ],
            "result_info": {"total_pages": 1}
        })
        records = server.get_records()
        assert "1.2.3.4 nas.home" in records["A"]
        assert "alias.home -> nas.home" in records["CNAME"]

    def test_add_record(self):
        server = _cloudflare()
        server.session = MagicMock()
        server.session.post.return_value = mock_resp(200, {"success": True})
        record = DNSRecord(domain="nas.home", value="1.2.3.4", type="A")
        assert server.add_record(record) is True

    def test_delete_record_looks_up_id_then_deletes(self):
        server = _cloudflare()
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(200, {
            "success": True,
            "result": [{"id": "rec-001"}]
        })
        server.session.delete.return_value = mock_resp(200, {"success": True})
        record = DNSRecord(domain="nas.home", value="1.2.3.4", type="A")
        assert server.delete_record(record) is True
        server.session.delete.assert_called_once()
        assert "rec-001" in server.session.delete.call_args[0][0]


# ---------------------------------------------------------------------------
# OPNsenseServer
# ---------------------------------------------------------------------------

class TestOPNsenseServer:
    def test_connect_success(self):
        server = _opnsense()
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(200)
        assert server.connect() is True

    def test_get_records_parses_hosts(self):
        server = _opnsense()
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(200, {
            "hosts": {
                "host": [
                    {"hostname": "nas", "domain": "home", "rr": {"a": "1.2.3.4"}},
                ]
            }
        })
        records = server.get_records()
        assert "1.2.3.4 nas.home" in records["A"]
        assert records["CNAME"] == set()

    def test_add_record(self):
        server = _opnsense()
        server.session = MagicMock()
        server.session.post.return_value = mock_resp(200)
        record = DNSRecord(domain="nas.home", value="1.2.3.4", type="A")
        assert server.add_record(record) is True
        payload = server.session.post.call_args[1]["json"]
        assert payload["host"]["hostname"] == "nas"
        assert payload["host"]["domain"] == "home"

    def test_add_record_ignores_cname(self):
        server = _opnsense()
        server.session = MagicMock()
        record = DNSRecord(domain="alias.home", value="nas.home", type="CNAME")
        assert server.add_record(record) is False
        server.session.post.assert_not_called()

    def test_delete_record_uses_uuid(self):
        server = _opnsense()
        server.session = MagicMock()
        server.session.get.return_value = mock_resp(200, {
            "rows": [{"hostname": "nas", "domain": "home", "uuid": "abc-123"}]
        })
        server.session.post.return_value = mock_resp(200)
        record = DNSRecord(domain="nas.home", value="1.2.3.4", type="A")
        assert server.delete_record(record) is True
        delete_url = server.session.post.call_args[0][0]
        assert "abc-123" in delete_url


# ---------------------------------------------------------------------------
# sync_records (base class logic)
# ---------------------------------------------------------------------------

class FakeServer(DNSServer):
    """Minimal concrete DNSServer for testing sync_records."""

    def __init__(self, name, a_records=None, cname_records=None):
        # bypass DNSServer.__init__ (avoids file I/O and credential loading)
        self.name = name
        self._a = set(a_records or [])
        self._cname = set(cname_records or [])
        self.added = []
        self.deleted = []
        self.timeout = 10
        self.retries = 3
        self.session = MagicMock()
        self.credentials = {}
        self.headers = {}

    def connect(self):
        return True

    def get_records(self):
        return {"A": self._a, "CNAME": self._cname}

    def add_record(self, record):
        self.added.append((record.type, record.domain, record.value))
        return True

    def delete_record(self, record):
        self.deleted.append((record.type, record.domain, record.value))
        return True


class TestSyncRecords:
    def test_adds_missing_records(self):
        hub = FakeServer("hub", a_records={"1.2.3.4 nas.home", "5.6.7.8 pi.home"})
        spoke = FakeServer("spoke", a_records={"1.2.3.4 nas.home"})
        stats = hub.sync_records(spoke)
        assert stats["added"] == 1
        assert stats["removed"] == 0
        assert len(spoke.added) == 1
        assert spoke.added[0] == ("A", "pi.home", "5.6.7.8")

    def test_removes_extra_records(self):
        hub = FakeServer("hub", a_records={"1.2.3.4 nas.home"})
        spoke = FakeServer("spoke", a_records={"1.2.3.4 nas.home", "9.9.9.9 stale.home"})
        stats = hub.sync_records(spoke)
        assert stats["added"] == 0
        assert stats["removed"] == 1
        assert len(spoke.deleted) == 1

    def test_dry_run_makes_no_mutations(self):
        hub = FakeServer("hub", a_records={"1.2.3.4 nas.home"})
        spoke = FakeServer("spoke", a_records={"9.9.9.9 stale.home"})
        stats = hub.sync_records(spoke, dry_run=True)
        assert stats["added"] == 1
        assert stats["removed"] == 1
        assert spoke.added == []
        assert spoke.deleted == []

    def test_syncs_cname_records(self):
        hub = FakeServer("hub", cname_records={"alias.home -> nas.home"})
        spoke = FakeServer("spoke")
        stats = hub.sync_records(spoke)
        assert stats["added"] == 1
        assert spoke.added[0] == ("CNAME", "alias.home", "nas.home")

    def test_no_op_when_already_in_sync(self):
        records = {"1.2.3.4 nas.home", "5.6.7.8 pi.home"}
        hub = FakeServer("hub", a_records=records)
        spoke = FakeServer("spoke", a_records=records.copy())
        stats = hub.sync_records(spoke)
        assert stats["added"] == 0
        assert stats["removed"] == 0
