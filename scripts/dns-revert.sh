#!/bin/bash
# Revert macOS DNS to automatic (DHCP-provided).
# Run this when stopping sing-box or switching back to normal networking.

set -euo pipefail

IFACE=$(route get default 2>/dev/null | awk '/interface:/{print $2}')
SERVICE=$(networksetup -listallhardwareports | awk -v iface="$IFACE" '
    /Hardware Port:/{port=$0; gsub("Hardware Port: ","",port)}
    /Device:/{dev=$2; if(dev==iface) print port}
')

if [ -z "$SERVICE" ]; then
    echo "ERROR: No active network service found"
    exit 1
fi

echo "Active interface: $IFACE -> $SERVICE"
echo "Reverting DNS to automatic..."
sudo networksetup -setdnsservers "$SERVICE" Empty

sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder 2>/dev/null || true

echo "Done. DNS restored to DHCP."
