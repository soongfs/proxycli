#!/bin/bash
# Set macOS DNS to a public IP that goes through sing-box TUN.
# The DNS queries will be hijacked by sing-box's hijack-dns rule
# and resolved via the proxy (fakeip + remote_dns chain).
#
# This works for 8.8.8.8, 1.1.1.1, or any public DNS IP.
# The actual DNS resolution is done by sing-box, not the upstream.
#
# Safety: run this AFTER sing-box daemon is started.
# If sing-box is stopped, DNS will fail — revert with dns-revert.sh.

set -euo pipefail

DNS_IP="${1:-8.8.8.8}"

# Detect network service
SERVICE=$(networksetup -listallnetworkservices | grep -v 'An asterisk' | head -1)
if [ -z "$SERVICE" ]; then
    echo "ERROR: No network service found"
    exit 1
fi

echo "Setting DNS on '$SERVICE' to $DNS_IP..."
sudo networksetup -setdnsservers "$SERVICE" "$DNS_IP"

# Flush DNS cache
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder 2>/dev/null || true

echo "Done. DNS set to $DNS_IP (hijacked by sing-box via TUN)"
echo "Revert with: $(dirname "$0")/dns-revert.sh"
