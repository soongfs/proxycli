#!/bin/bash
# Set macOS DNS to a public IP that goes through sing-box TUN.
# The DNS queries are hijacked by sing-box's hijack-dns route rule
# and resolved through direct_dns or remote_dns according to the generated config.
#
# Usage: sudo scripts/dns-proxy.sh [DNS_IP]
#   Default DNS_IP: 8.8.8.8 (also works with 1.1.1.1, etc.)
#
# Safety: run this AFTER sing-box daemon is started.
# Revert with: sudo scripts/dns-revert.sh

set -euo pipefail

DNS_IP="${1:-8.8.8.8}"

# Detect active interface (en0, en1, etc.)
IFACE=$(route get default 2>/dev/null | awk '/interface:/{print $2}')
# Map interface name to service name
SERVICE=$(networksetup -listallhardwareports | awk -v iface="$IFACE" '
    /Hardware Port:/{port=$0; gsub("Hardware Port: ","",port)}
    /Device:/{dev=$2; if(dev==iface) print port}
')

if [ -z "$SERVICE" ]; then
    echo "ERROR: No active network service found"
    exit 1
fi

echo "Active interface: $IFACE -> $SERVICE"
echo "Setting DNS to $DNS_IP..."
sudo networksetup -setdnsservers "$SERVICE" "$DNS_IP"

# Flush DNS cache
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder 2>/dev/null || true

echo "Done. DNS set to $DNS_IP (hijacked by sing-box via TUN)"
echo "Revert with: $(dirname "$0")/dns-revert.sh"
