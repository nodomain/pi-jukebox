#!/usr/bin/env bash
# Pair Bluetooth speaker and enable overlay FS.
# Run after setup.sh + reboot, with speaker in pairing mode.
#
# Run as root: sudo ./pair-bt.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -f "${SCRIPT_DIR}/.env" ]]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in your values."
    exit 1
fi
source "${SCRIPT_DIR}/.env"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Run as root (sudo ./pair-bt.sh)"
    exit 1
fi

echo "==> Powering on Bluetooth"
rfkill unblock bluetooth
bluetoothctl power on

echo "==> Scanning for ${BT_DEVICE_NAME} (15 seconds)..."
timeout 15 bluetoothctl scan on 2>&1 | grep -i "${BT_MAC}" || true

echo "==> Pairing with ${BT_MAC}"
bluetoothctl pair "${BT_MAC}"
sleep 2

echo "==> Trusting ${BT_MAC}"
bluetoothctl trust "${BT_MAC}"
sleep 2

echo "==> Connecting to ${BT_MAC}"
bluetoothctl connect "${BT_MAC}" || echo "NOTE: Connect failed, watchdog will handle this after reboot."
sleep 3

echo "==> Verifying connection"
if bluetoothctl info "${BT_MAC}" | grep -q "Connected: yes"; then
    echo "Connected!"
else
    echo "Not connected yet — this is normal. Watchdog will connect after reboot."
fi

echo "==> Enabling overlay filesystem (read-only root)"
raspi-config nonint enable_overlayfs
raspi-config nonint enable_bootro

echo ""
echo "=== Done! Rebooting in 5 seconds ==="
echo "After reboot, the Pi will auto-connect to ${BT_DEVICE_NAME} and stream via Bluetooth."
sleep 5
reboot
