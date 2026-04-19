#!/usr/bin/env bash
# Jukebox Pi Setup Script
# Provisions a fresh Raspberry Pi OS Lite (64-bit) as a Snapcast client
# with Bluetooth A2DP output.
#
# Run as root: sudo ./setup.sh
#
# After reboot, run pair-bt.sh to pair the speaker.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -f "${SCRIPT_DIR}/.env" ]]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in your values."
    exit 1
fi
source "${SCRIPT_DIR}/.env"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Run as root (sudo ./setup.sh)"
    exit 1
fi

echo "==> Configuring passwordless sudo for ${JUKEBOX_USER}"
echo "${JUKEBOX_USER} ALL=(ALL) NOPASSWD: ALL" > "/etc/sudoers.d/${JUKEBOX_USER}"
chmod 440 "/etc/sudoers.d/${JUKEBOX_USER}"

echo "==> Adding ${JUKEBOX_USER} to bluetooth group"
usermod -aG bluetooth "${JUKEBOX_USER}"

echo "==> Enabling user linger for ${JUKEBOX_USER}"
loginctl enable-linger "${JUKEBOX_USER}"

echo "==> Installing packages"
apt-get update -qq
apt-get install -y -qq snapclient bluez pipewire pipewire-pulse wireplumber \
    libspa-0.2-bluetooth pulseaudio-utils rfkill

echo "==> Configuring snapclient"
cat > /etc/default/snapclient << EOF
SNAPCLIENT_OPTS="--host ${SNAPCAST_SERVER} --player pulse"
EOF

mkdir -p /etc/systemd/system/snapclient.service.d
UID_NUM=$(id -u "${JUKEBOX_USER}")
cat > /etc/systemd/system/snapclient.service.d/override.conf << EOF
[Service]
User=${JUKEBOX_USER}
Group=${JUKEBOX_USER}
Environment=PULSE_RUNTIME_PATH=/run/user/${UID_NUM}/pulse
EOF

echo "==> Configuring Bluetooth"
sed -i 's/^#AutoEnable.*/AutoEnable=true/' /etc/bluetooth/main.conf
sed -i 's/^AutoEnable=false/AutoEnable=true/' /etc/bluetooth/main.conf

echo "==> Disabling WiFi power save (reduces audio latency)"
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/wifi-powersave.conf << 'EOF'
[connection]
wifi.powersave = 2
EOF

echo "==> Disabling WirePlumber seat monitoring (headless fix)"
mkdir -p /etc/wireplumber/wireplumber.conf.d
cat > /etc/wireplumber/wireplumber.conf.d/50-bluez-no-seat.conf << 'EOF'
wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}
EOF

echo "==> Creating Bluetooth watchdog"
cat > /usr/local/bin/bt-watchdog << EOF
#!/usr/bin/env bash
MAC="${BT_MAC}"
sleep 10
while true; do
    if ! bluetoothctl info "\$MAC" 2>/dev/null | grep -q 'Connected: yes'; then
        bluetoothctl connect "\$MAC" 2>/dev/null
    fi
    sleep 15
done
EOF
chmod +x /usr/local/bin/bt-watchdog

cat > /etc/systemd/system/bt-autoconnect.service << EOF
[Unit]
Description=Auto-connect to ${BT_DEVICE_NAME} via Bluetooth
After=bluetooth.service
Wants=bluetooth.service

[Service]
ExecStart=/usr/local/bin/bt-watchdog
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable snapclient bt-autoconnect bluetooth

echo "==> Disabling unnecessary timers"
systemctl disable --now \
    apt-daily.timer \
    apt-daily-upgrade.timer \
    man-db.timer \
    fstrim.timer \
    e2scrub_all.timer \
    2>/dev/null || true

echo ""
echo "=== Base setup complete ==="
echo "Next steps:"
echo "  1. Reboot: sudo reboot"
echo "  2. Put ${BT_DEVICE_NAME} in Bluetooth pairing mode"
echo "  3. Run: sudo ./pair-bt.sh"
echo ""
