#!/usr/bin/env bash
# Cross-compile RTL8812AU WiFi driver for Raspberry Pi
#
# Builds the kernel module on the dev machine using Docker with an ARM64
# Debian container, then copies the .ko file to the Pi and installs it.
#
# Prerequisites:
#   - Docker Desktop running on the dev machine
#   - SSH access to the Pi (uses JUKEBOX_USER/JUKEBOX_HOST from .env)
#   - linux-headers installed on the Pi (matching kernel version)
#
# Usage:
#   ./scripts/build-wifi-driver.sh
#
# What it does:
#   1. Fetches kernel version and headers path from the Pi
#   2. Copies kernel headers to a local temp dir
#   3. Clones the rtl8812au driver source
#   4. Builds the .ko module in a Docker ARM64 container
#   5. Copies the module to the Pi and loads it
#   6. Configures NetworkManager to prefer the USB adapter on 5GHz

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/../.env"

HOST="${JUKEBOX_USER}@${JUKEBOX_HOST}"
WORKDIR="/tmp/wifi-driver-build"
DRIVER_REPO="https://github.com/aircrack-ng/rtl8812au.git"

echo "==> Fetching kernel info from Pi"
KVER=$(ssh "$HOST" "uname -r")
echo "  Kernel: $KVER"

echo "==> Copying kernel headers from Pi (resolving all symlinks)"
rm -rf "$WORKDIR"
mkdir -p "$WORKDIR/kernel-src"
# Copy common headers first (base), then version-specific on top
COMMON_DIR=$(ssh "$HOST" "readlink -f /usr/src/linux-headers-*-common-rpi 2>/dev/null | head -1")
echo "  Common: $COMMON_DIR"
rsync -azL "$HOST:$COMMON_DIR/" "$WORKDIR/kernel-src/"
# Version-specific headers overlay (includes .config, Module.symvers, etc.)
rsync -azL --exclude='Makefile' "$HOST:/usr/src/linux-headers-$KVER/" "$WORKDIR/kernel-src/"

echo "==> Cloning rtl8812au driver"
git clone --depth 1 "$DRIVER_REPO" "$WORKDIR/rtl8812au"

echo "==> Building kernel module in Docker (ARM64)"
docker run --rm --platform linux/arm64 \
  -v "$WORKDIR/kernel-src:/ksrc" \
  -v "$WORKDIR/rtl8812au:/driver" \
  -w /driver \
  debian:trixie-slim \
  bash -c "
    apt-get update -qq && apt-get install -y -qq build-essential bc kmod > /dev/null 2>&1
    # Patch the Makefile to use local path instead of absolute /usr/src reference
    sed -i 's|include /usr/src/.*/Makefile|include /ksrc/Makefile|' /ksrc/Makefile 2>/dev/null || true
    make KSRC=/ksrc ARCH=arm64 -j\$(nproc) 2>&1 | tail -10
    ls -la 88*.ko 2>/dev/null || ls -la *.ko 2>/dev/null
  "

MODULE="$WORKDIR/rtl8812au/88x2bu.ko"
if [[ ! -f "$MODULE" ]]; then
  # Try alternate module name
  MODULE=$(find "$WORKDIR/rtl8812au" -name '*.ko' | head -1)
fi

if [[ -z "$MODULE" || ! -f "$MODULE" ]]; then
  echo "ERROR: Module not found after build"
  exit 1
fi

MODULE_NAME=$(basename "$MODULE")
echo "==> Built: $MODULE_NAME"

echo "==> Copying module to Pi"
scp "$MODULE" "$HOST:/tmp/$MODULE_NAME"

echo "==> Configuring module for auto-load on boot"
ssh "$HOST" "
  sudo mkdir -p /lib/modules/$KVER/extra
  sudo cp /tmp/$MODULE_NAME /lib/modules/$KVER/extra/
  sudo depmod -a
  sudo modprobe \$(basename $MODULE_NAME .ko)
  echo '  Module loaded'
  ip link show | grep wlan
  echo ''
  echo 'Run setup.sh again to configure NetworkManager for the USB adapter.'
"

echo ""
echo "=== Done ==="
echo "Next steps:"
echo "  1. Run setup.sh on the Pi to configure NetworkManager"
echo "  2. Reboot: ssh $HOST 'sudo reboot'"
echo ""

# Cleanup
rm -rf "$WORKDIR"
