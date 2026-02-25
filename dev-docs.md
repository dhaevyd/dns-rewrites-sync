# 🛠️ DNS Rewrites Sync - Development Documentation

## 📊 Current Status (v1.0.0)

### ✅ Completed Features

#### Core Infrastructure
- [x] Modular project structure
- [x] Secure credential storage with master key encryption
- [x] SQLite database for sync history
- [x] Configuration management
- [x] CLI framework with argparse
- [x] Logging system

#### Server Implementations

| Server | Status | Auth | Records | Testing |
|--------|--------|------|---------|---------|
| **Pi-hole v6+** | ✅ Complete | Password | A, CNAME | Unit tests ✅ |
| **AdGuard Home** | ✅ Complete | Username/Pass | A, CNAME | Unit tests ✅ |
| **Cloudflare DNS** | ✅ Complete | API Token | A, CNAME, TXT | Unit tests ✅ |
| **OPNsense/pfSense** | ✅ Complete | API Key/Secret | A | Unit tests ✅ |
| **Unbound** | ✅ Complete | API Key | A, CNAME | Unit tests ✅ |
| **Generic API** | ✅ Complete | Configurable | Configurable | Unit tests ✅ |

#### Features
- [x] Master key initialization
- [x] Interactive server addition
- [x] Server list/remove/test commands
- [x] Dry-run mode
- [x] Sync engine with record comparison
- [x] Unit test suite (15+ tests)
- [x] Docker support
- [x] Installer script

### 🚧 In Progress / Next Steps

#### High Priority
- [ ] **Systemd Service** - Create proper service file with auto-start
- [ ] **Sync Scheduling** - Built-in cron/scheduler
- [ ] **Webhook Notifications** - Slack/Discord/Email on sync events
- [ ] **Conflict Resolution UI** - Manual conflict queue

#### Medium Priority
- [ ] **Web UI Dashboard** - Flask/FastAPI + React
- [ ] **Prometheus Metrics** - Export sync metrics
- [ ] **Grafana Dashboard** - Pre-built dashboard
- [ ] **Backup/Restore** - Export/import configuration
- [ ] **Multi-user Support** - Role-based access

#### Low Priority / Future
- [ ] **REST API** - For remote management
- [ ] **Kubernetes Operator** - CRD for DNS sync
- [ ] **Terraform Provider** - Infrastructure as code
- [ ] **More Server Types** - Bind9, PowerDNS, Route53
- [ ] **LDAP/AD Integration** - Enterprise auth

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                      CLI (argparse)                  │
├─────────────────────────────────────────────────────┤
│                   Command Router                     │
├──────────┬──────────┬──────────┬──────────┬─────────┤
│   init   │ add-server│ list     │  sync    │ status  │
├──────────┴──────────┴──────────┴──────────┴─────────┤
│                    Core Engine                        │
├─────────────────────────────────────────────────────┤
│   Config Mgr  │  Secrets Mgr  │  Sync Engine         │
├─────────────────────────────────────────────────────┤
│                   Server Factory                      │
├──────────┬──────────┬──────────┬──────────┬─────────┤
│  Pi-hole │  AdGuard │ Cloudflare│ OPNsense │ Generic │
└──────────┴──────────┴──────────┴──────────┴─────────┘
```

## 📁 Project Structure

```
dns-rewrites-sync/
├── dns_sync/
│   ├── __init__.py
│   ├── cli.py              # CLI commands
│   ├── config.py           # Config management
│   ├── secrets.py          # Encryption
│   ├── registry.py         # Server registry
│   ├── sync.py             # Sync engine
│   ├── database.py         # SQLite tracking
│   └── servers/
│       ├── __init__.py
│       ├── base.py         # Base server class
│       ├── pihole.py
│       ├── adguard.py
│       ├── cloudflare.py
│       ├── opnsense.py
│       ├── unbound.py
│       └── generic.py
├── scripts/
│   └── install.sh          # Installer
├── tests/
│   └── test_servers.py     # Unit tests
├── docs/                    # Documentation
├── setup.py
├── requirements.txt
└── README.md
```

## 🔧 How to Continue Development

### 1. Setting Up Development Environment

```bash
# Clone the repo
git clone https://github.com/dhaevyd/dns-rewrites-sync.git
cd dns-rewrites-sync

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install in development mode
pip install -e .
pip install -r requirements-dev.txt  # pytest, black, mypy, etc.

# Run tests
pytest tests/ -v

# Run with live config (if you have servers)
dns-sync init
dns-sync add-server  # Add your test servers
dns-sync status
```

### 2. Code Style & Standards

```bash
# Format code
black dns_sync/

# Type checking
mypy dns_sync/

# Linting
flake8 dns_sync/

# Run all tests with coverage
pytest --cov=dns_sync tests/ --cov-report=html
```

### 3. Adding a New Server Type

1. Create new file in `dns_sync/servers/` (e.g., `bind9.py`)
2. Implement all required methods from `base.py`:
   - `connect()`
   - `get_records()`
   - `add_record()`
   - `delete_record()`
3. Add to registry in `registry.py`
4. Add to factory in `servers/__init__.py`
5. Write unit tests in `tests/test_servers.py`
6. Update README with new server type

**Template for new server:**

```python
"""New DNS server implementation"""

from typing import Dict, Set
from .base import DNSServer, DNSRecord

class NewServer(DNSServer):
    """Description of new server"""
    
    def __init__(self, name: str, config: dict, secrets):
        super().__init__(name, config, secrets)
        # Server-specific initialization
    
    def connect(self) -> bool:
        """Implement connection logic"""
        pass
    
    def get_records(self) -> Dict[str, Set[str]]:
        """Fetch and parse records"""
        pass
    
    def add_record(self, record: DNSRecord) -> bool:
        """Add record"""
        pass
    
    def delete_record(self, record: DNSRecord) -> bool:
        """Delete record"""
        pass
```

### 4. Adding New Features

#### A. Sync Scheduler
```python
# In dns_sync/scheduler.py
class SyncScheduler:
    def __init__(self, config):
        self.schedule = config.get('schedule', '0 * * * *')
        self.jobs = []
    
    def add_job(self, server_name: str, interval: str):
        """Add sync job"""
        pass
    
    def start(self):
        """Start scheduler thread"""
        pass
```

#### B. Webhook Notifications
```python
# In dns_sync/notifications.py
class WebhookNotifier:
    def __init__(self, config):
        self.url = config['url']
        self.headers = config.get('headers', {})
    
    def send(self, event: str, data: dict):
        """Send webhook notification"""
        pass
```

#### C. Prometheus Metrics
```python
# In dns_sync/metrics.py
from prometheus_client import Counter, Gauge, Histogram

sync_total = Counter('dns_sync_total', 'Total syncs')
records_gauge = Gauge('dns_records', 'Records per server', ['server', 'type'])
sync_duration = Histogram('dns_sync_duration_seconds', 'Sync duration')
```

### 5. Testing Strategy

```bash
# Unit tests (mock all external calls)
pytest tests/test_servers.py

# Integration tests (with real servers, requires config)
INTEGRATION_TEST=1 pytest tests/test_integration.py

# Load tests (simulate many records)
LOAD_TEST=1 python tests/test_load.py

# Security audit
bandit -r dns_sync/
safety check
```

### 6. Building for Distribution

```bash
# Build package
python setup.py sdist bdist_wheel

# Test package
twine check dist/*

# Upload to PyPI (if desired)
twine upload dist/*

# Build Docker image
docker build -t dns-rewrites-sync:latest .
docker tag dns-rewrites-sync:latest ghcr.io/dhaevyd/dns-rewrites-sync:1.0.0
docker push ghcr.io/dhaevyd/dns-rewrites-sync:1.0.0
```

## 🎯 Roadmap to v2.0

### v1.1 (Next Release)
- [ ] Systemd service integration
- [ ] Sync scheduling (cron-like)
- [ ] Webhook notifications
- [ ] Better error handling with retries
- [ ] Sync history viewer CLI

### v1.2
- [ ] Web UI (read-only dashboard)
- [ ] Prometheus metrics
- [ ] Rate limiting per server
- [ ] Conflict resolution strategies

### v1.3
- [ ] REST API
- [ ] Multi-user support
- [ ] Backup/restore commands
- [ ] Performance optimizations

### v2.0
- [ ] Full Web UI with management
- [ ] Grafana dashboards
- [ ] Kubernetes operator
- [ ] Terraform provider
- [ ] Enterprise features (audit logs, SSO)

## 🤔 Known Issues & Limitations

1. **CNAME Target Resolution** - Some servers handle CNAME targets differently
2. **Rate Limiting** - Cloudflare and other APIs have rate limits
3. **Large Deployments** - Need batching for 1000+ records
4. **Concurrent Sync** - Not yet supported (planned for v1.3)

## 📚 Documentation Needs

- [ ] API reference for each server type
- [ ] Advanced configuration examples
- [ ] Troubleshooting guide
- [ ] Migration guide from v0.x
- [ ] Security best practices

## 🤝 How to Contribute

1. Fork the repository
2. Create a feature branch
3. Write tests for new features
4. Submit pull request
5. Sign CLA (coming soon)

## 📞 Getting Help

- **Issues**: GitHub Issues
- **Discussions**: GitHub Discussions
- **Discord**: [Link TBD]
- **Email**: dev@dns-sync.io (future)

## 📝 License & Legal

MIT License - See LICENSE file

---

**Current Commit**: [abc123] - All 6 server types implemented, tests passing
**Last Updated**: 2026-02-25
**Lead Maintainer**: @dhaevyd

*This document reflects the state of the project as of v1.0.0*