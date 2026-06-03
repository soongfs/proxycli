#!/bin/bash
# Revert macOS DNS to automatic (DHCP-provided).
# Run this when stopping sing-box or switching back to normal networking.

set -euo pipefail

SERVICE=$(networksetup -listallnetworkservices | grep -v 'An asterisk' | head -1)
if [ -z "$SERVICE" ]; then
    echo "ERROR: No network service found"
    exit 1
fi

echo "Reverting DNS on '$SERVICE' to automatic..."
sudo networksetup -setdnsservers "$SERVICE" Empty

# Flush DNS cache
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder 2>/dev/null || true

echo "Done. DNS restored to DHCP."
