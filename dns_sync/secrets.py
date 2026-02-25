"""Secure credential storage with master key"""

import os
import base64
import getpass
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class SecretsManager:
    """Manages encrypted credentials"""
    
    def __init__(self, config_dir="/etc/dns-sync"):
        self.config_dir = config_dir
        self.secrets_dir = os.path.join(config_dir, "secrets")
        self.key_file = os.path.join(config_dir, "master.key")
        self._ensure_dirs()
        self.cipher = None
    
    def _ensure_dirs(self):
        """Create config directories if they don't already exist."""
        for path in (self.config_dir, self.secrets_dir):
            if not os.path.exists(path):
                try:
                    os.makedirs(path, mode=0o770, exist_ok=True)
                except PermissionError:
                    print(f"❌ Cannot access {path}")
                    print("   Either run as root for first-time setup, or ensure you are")
                    print("   in the 'dns-sync' group and have logged out and back in.")
                    raise SystemExit(1)
    
    def init_master_key(self, password=None):
        """Initialize master key (first run)"""
        if not password:
            print("\n🔐 Initialize Master Key")
            print("=" * 40)
            password = getpass.getpass("Create master password: ")
            confirm = getpass.getpass("Confirm master password: ")
            
            if password != confirm:
                print("❌ Passwords don't match!")
                return False
        
        # Generate key from password
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        
        # Save salt and key
        with open(self.key_file + ".salt", 'wb') as f:
            f.write(salt)
        
        with open(self.key_file, 'wb') as f:
            f.write(key)
        
        os.chmod(self.key_file, 0o600)
        os.chmod(self.key_file + ".salt", 0o600)
        
        self.cipher = Fernet(key)
        print("✅ Master key created successfully!")
        print("   Store this password safely - it CANNOT be recovered!")
        return True
    
    def load_master_key(self, password=None):
        """Load master key (normal operation).

        When called without a password (e.g. from a systemd service), the
        derived key stored in master.key is loaded directly — no TTY needed.
        Pass a password explicitly only when re-deriving (e.g. change-master-key).
        """
        if not os.path.exists(self.key_file):
            return False

        if password is None:
            # The derived Fernet key is already persisted; load it directly.
            with open(self.key_file, 'rb') as f:
                key = f.read()
            self.cipher = Fernet(key)
        else:
            # Re-derive from password (used for key rotation).
            with open(self.key_file + ".salt", 'rb') as f:
                salt = f.read()
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=480000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            self.cipher = Fernet(key)

        # Verify against test token if present
        test_file = os.path.join(self.secrets_dir, ".test")
        if os.path.exists(test_file):
            try:
                with open(test_file, 'rb') as f:
                    self.cipher.decrypt(f.read())
            except Exception:
                print("❌ Invalid master key!")
                self.cipher = None
                return False

        return True
    
    def set_credential(self, server_name, field, value):
        """Encrypt and store a credential"""
        if not self.cipher:
            raise Exception("Master key not loaded")
        
        # Encrypt the value
        encrypted = self.cipher.encrypt(value.encode())
        
        # Save to file
        file_path = os.path.join(self.secrets_dir, f"{server_name}_{field}.enc")
        with open(file_path, 'wb') as f:
            f.write(encrypted)
        
        os.chmod(file_path, 0o600)
        return True
    
    def get_credential(self, server_name, field):
        """Retrieve and decrypt a credential"""
        if not self.cipher:
            raise Exception("Master key not loaded")
        
        file_path = os.path.join(self.secrets_dir, f"{server_name}_{field}.enc")
        
        if not os.path.exists(file_path):
            return None
        
        with open(file_path, 'rb') as f:
            encrypted = f.read()
        
        return self.cipher.decrypt(encrypted).decode()
    
    def remove_credential(self, server_name, field):
        """Remove a credential"""
        file_path = os.path.join(self.secrets_dir, f"{server_name}_{field}.enc")
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
    
    def list_servers(self):
        """List all servers with stored credentials"""
        servers = set()
        for file in os.listdir(self.secrets_dir):
            if file.endswith('.enc'):
                server = file.rsplit('_', 1)[0]
                servers.add(server)
        return sorted(list(servers))