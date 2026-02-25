"""Command line interface"""

import argparse
import sys
import getpass
from tabulate import tabulate
from .config import ConfigManager
from .secrets import SecretsManager
from .registry import get_server_types, get_auth_fields
from .servers import create_server

class CLI:
    def __init__(self):
        self.config = None
        self.secrets = None
        self.parser = self._create_parser()
    
    def _create_parser(self):
        parser = argparse.ArgumentParser(
            description="DNS Rewrites Sync - Universal DNS synchronization tool"
        )
        subparsers = parser.add_subparsers(dest='command', help='Commands')
        
        # init command
        init_parser = subparsers.add_parser('init', help='Initialize master key')
        
        # add-server command
        add_parser = subparsers.add_parser('add-server', help='Add a new DNS server')
        add_parser.add_argument('--name', help='Server name')
        add_parser.add_argument('--type', help='Server type')
        
        # list-servers command
        subparsers.add_parser('list-servers', help='List configured servers')
        
        # remove-server command
        remove_parser = subparsers.add_parser('remove-server', help='Remove a server')
        remove_parser.add_argument('name', help='Server name')
        
        # test-server command
        test_parser = subparsers.add_parser('test-server', help='Test server connection')
        test_parser.add_argument('name', help='Server name')
        
        # status command
        subparsers.add_parser('status', help='Show sync status')
        
        # sync command
        sync_parser = subparsers.add_parser('sync', help='Run sync')
        sync_parser.add_argument('--server', help='Specific server to sync')
        sync_parser.add_argument('--dry-run', action='store_true', help='Preview only')
        
        return parser
    
    def run(self):
        args = self.parser.parse_args()

        if not args.command:
            self.parser.print_help()
            return

        # Initialise managers now that we know a command is actually running
        self.config = ConfigManager()
        self.secrets = SecretsManager()

        # Handle init separately (doesn't need master key)
        if args.command == 'init':
            self._cmd_init()
            return

        # All other commands need master key
        if not self.secrets.load_master_key():
            print("❌ Master key not initialized. Run 'dns-sync init' first")
            return
        
        # Route to appropriate command
        commands = {
            'add-server': self._cmd_add_server,
            'list-servers': self._cmd_list_servers,
            'remove-server': self._cmd_remove_server,
            'test-server': self._cmd_test_server,
            'status': self._cmd_status,
            'sync': self._cmd_sync,
        }
        
        if args.command in commands:
            commands[args.command](args)
        else:
            print(f"Unknown command: {args.command}")
    
    def _cmd_init(self):
        """Initialize master key"""
        self.secrets.init_master_key()
    
    def _cmd_add_server(self, args):
        """Interactive server addition"""
        print("\n🆕 Add New DNS Server")
        print("=" * 50)
        
        # Show server types
        print("\nAvailable server types:")
        types = get_server_types()
        for i, (key, name, desc) in enumerate(types, 1):
            print(f"  {i}) {name} - {desc}")
        
        # Get type
        choice = input("\nSelect type [1]: ") or "1"
        try:
            server_type = types[int(choice)-1][0]
        except:
            print("❌ Invalid choice")
            return
        
        # Get name
        name = args.name or input("Server name: ")
        if self.config.get_server(name):
            print(f"❌ Server '{name}' already exists")
            return
        
        # Get URL
        url = input("URL: ").rstrip('/')
        
        # Get auth fields
        auth_fields = get_auth_fields(server_type)
        auth_data = {}
        
        print("\n🔑 Authentication")
        for field in auth_fields:
            prompt = f"{field['prompt']}"
            if field.get('optional'):
                prompt += " (optional)"
            prompt += ": "
            
            if field['type'] == 'password':
                value = getpass.getpass(prompt)
            else:
                value = input(prompt)
            
            if value or not field.get('optional'):
                # Store encrypted
                self.secrets.set_credential(name, field['name'], value)
                auth_data[field['name']] = f"encrypted:{field['name']}"
        
        # Additional options
        print("\n⚙️  Options")
        sync_mode = input("Sync mode (hub/spoke) [spoke]: ") or "spoke"
        enabled = input("Enable now? (Y/n): ").lower() != 'n'
        
        # Save config
        server_config = {
            "name": name,
            "type": server_type,
            "url": url,
            "auth": auth_data,
            "sync_mode": sync_mode,
            "enabled": enabled
        }
        
        self.config.add_server(server_config)
        print(f"\n✅ Server '{name}' added successfully!")
        
        # Test connection
        test = input("\nTest connection now? (Y/n): ").lower() != 'n'
        if test:
            self._test_server(name)
    
    def _cmd_list_servers(self, args):
        """List configured servers"""
        servers = self.config.list_servers()
        
        if not servers:
            print("No servers configured. Run 'dns-sync add-server' first")
            return
        
        table = []
        for s in servers:
            status = "✅" if s.get('enabled', True) else "⏸️"
            table.append([
                status,
                s['name'],
                s['type'],
                s['url'],
                s.get('sync_mode', 'spoke')
            ])
        
        print("\n📋 Configured Servers")
        print(tabulate(table, headers=['', 'Name', 'Type', 'URL', 'Mode'], tablefmt='simple'))
    
    def _cmd_remove_server(self, args):
        """Remove a server"""
        server = self.config.get_server(args.name)
        if not server:
            print(f"❌ Server '{args.name}' not found")
            return
        
        print(f"\n⚠️  WARNING: This will remove server '{args.name}' and its credentials")
        confirm = input(f"Type the server name to confirm: ")
        
        if confirm == args.name:
            # Remove credentials
            for field in server['auth'].keys():
                self.secrets.remove_credential(args.name, field)
            
            # Remove config
            self.config.remove_server(args.name)
            print(f"✅ Server '{args.name}' removed")
        else:
            print("❌ Cancelled")
    
    def _cmd_test_server(self, args):
        """Test server connection"""
        self._test_server(args.name)
    
    def _test_server(self, name):
        """Test a specific server"""
        server_config = self.config.get_server(name)
        if not server_config:
            print(f"❌ Server '{name}' not found")
            return False
        
        print(f"\n🔌 Testing connection to '{name}'...")
        
        # Create server instance
        server = create_server(server_config['type'], server_config['name'], server_config, self.secrets)
        
        # Test connection
        if server.test_connection():
            print("✅ Connection successful!")
            
            # Get record count
            try:
                records = server.get_records()
                total = sum(len(r) for r in records.values())
                print(f"📊 Found {total} records")
                return True
            except:
                print("⚠️  Connected but couldn't fetch records")
                return False
        else:
            print("❌ Connection failed")
            return False
    
    def _cmd_status(self, args):
        """Show sync status"""
        servers = self.config.list_servers()
        
        print("\n📊 DNS Rewrites Sync Status")
        print("=" * 50)
        
        for server in servers:
            if not server.get('enabled', True):
                print(f"⏸️  {server['name']} (disabled)")
                continue
            
            # Test connection quickly
            try:
                s = create_server(server['type'], server['name'], server, self.secrets)
                if s.test_connection():
                    records = s.get_records()
                    total = sum(len(r) for r in records.values())
                    print(f"✅ {server['name']}: {total} records")
                else:
                    print(f"❌ {server['name']}: offline")
            except:
                print(f"❌ {server['name']}: error")
    
    def _cmd_sync(self, args):
        """Run sync"""
        servers = self.config.list_servers()
        enabled = [s for s in servers if s.get('enabled', True)]

        hubs = [s for s in enabled if s.get('sync_mode') == 'hub']
        spokes = [s for s in enabled if s.get('sync_mode') != 'hub']

        if not hubs:
            print("❌ No hub server configured. Set sync_mode: hub on one server.")
            return

        if args.server:
            spokes = [s for s in spokes if s['name'] == args.server]
            if not spokes:
                print(f"❌ Server '{args.server}' not found or is not a spoke")
                return

        if not spokes:
            print("No spoke servers to sync.")
            return

        if args.dry_run:
            print("(dry run - no changes will be made)\n")

        total_added = 0
        total_removed = 0

        for hub_cfg in hubs:
            hub = create_server(hub_cfg['type'], hub_cfg['name'], hub_cfg, self.secrets)
            print(f"Connecting to hub '{hub_cfg['name']}'...")
            if not hub.test_connection():
                print(f"❌ Cannot reach hub '{hub_cfg['name']}', skipping")
                continue

            for spoke_cfg in spokes:
                spoke = create_server(spoke_cfg['type'], spoke_cfg['name'], spoke_cfg, self.secrets)
                print(f"  → Syncing to '{spoke_cfg['name']}'...", end=' ', flush=True)
                if not spoke.test_connection():
                    print("unreachable, skipping")
                    continue
                stats = hub.sync_records(spoke, dry_run=args.dry_run)
                total_added += stats['added']
                total_removed += stats['removed']
                print(f"+{stats['added']} added, -{stats['removed']} removed")

        print(f"\n✅ Sync complete: +{total_added} added, -{total_removed} removed")

def main():
    cli = CLI()
    cli.run()

if __name__ == "__main__":
    main()