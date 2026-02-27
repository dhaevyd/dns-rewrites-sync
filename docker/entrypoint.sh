#!/bin/bash
set -e
# Fix ownership of the data volume so appuser can write to it
chown -R appuser:appuser /var/lib/dns-sync
# Fix ownership of config/secrets so appuser can read encrypted credentials
chown -R appuser:appuser /etc/dns-sync
# Drop privileges and exec the main process
exec gosu appuser "$@"
