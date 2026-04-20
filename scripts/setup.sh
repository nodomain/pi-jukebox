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
    libspa-0.2-bluetooth pulseaudio-utils rfkill cava

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

echo "==> Creating WiFi roaming helper"
cat > /usr/local/bin/wifi-roam << 'ROAM'
#!/usr/bin/env bash
# WiFi roaming helper - checks signal strength and triggers rescan if weak
THRESHOLD=-70
IFACE=wlan0
while true; do
    SIGNAL=$(iw dev $IFACE link 2>/dev/null | grep signal | awk '{print $2}')
    if [ -n "$SIGNAL" ] && [ "$SIGNAL" -lt "$THRESHOLD" ] 2>/dev/null; then
        nmcli device wifi rescan ifname $IFACE 2>/dev/null
        sleep 5
        nmcli device wifi connect --ifname $IFACE 2>/dev/null || true
    fi
    sleep 30
done
ROAM
chmod +x /usr/local/bin/wifi-roam

cat > /etc/systemd/system/wifi-roam.service << 'EOF'
[Unit]
Description=WiFi roaming helper
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
ExecStart=/usr/local/bin/wifi-roam
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
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

echo "==> Configuring SBC-XQ codec preference"
cat > /etc/wireplumber/wireplumber.conf.d/51-bluez-sbc-xq.conf << 'EOF'
monitor.bluez.rules = [
  {
    matches = [
      { device.name = "~bluez_card.*" }
    ]
    actions = {
      update-props = {
        bluez5.a2dp.codec = [ sbc_xq sbc ]
        bluez5.auto-connect = [ a2dp_sink ]
      }
    }
  }
]

device.profile.priority.rules = [
  {
    matches = [
      { device.name = "~bluez_card.*" }
    ]
    actions = {
      set-profile-priorities = [
        { name = "a2dp-sink-sbc_xq", priority = 10000 }
        { name = "a2dp-sink", priority = 5000 }
      ]
    }
  }
]
EOF

echo "==> Reducing SD card writes"
# tmpfs for log and tmp
FSTAB_ROOT=$(grep 'PARTUUID.*/$' /etc/fstab || grep 'PARTUUID.*/[[:space:]]' /etc/fstab | head -1)
ROOT_UUID=$(echo "$FSTAB_ROOT" | awk '{print $1}')
BOOT_UUID=$(grep 'boot/firmware' /etc/fstab | awk '{print $1}')
cat > /etc/fstab << EOF
proc            /proc           proc    defaults          0       0
${BOOT_UUID}  /boot/firmware  vfat    defaults          0       2
${ROOT_UUID}  /               ext4    defaults,noatime,commit=120  0       1
tmpfs           /var/log        tmpfs   defaults,noatime,nosuid,nodev,noexec,size=20m  0  0
tmpfs           /var/tmp        tmpfs   defaults,noatime,nosuid,nodev,size=20m  0  0
EOF

# Volatile journal (RAM only)
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/volatile.conf << 'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=10M
EOF

echo "==> Creating Bluetooth watchdog"
CARD_NAME="bluez_card.${BT_MAC//:/_}"
cat > /usr/local/bin/bt-watchdog << WATCHDOG
#!/usr/bin/env bash
MAC="${BT_MAC}"
CARD="${CARD_NAME}"
PW_ENV="XDG_RUNTIME_DIR=/run/user/${UID_NUM}"
WAS_CONNECTED=false
sleep 10
# Initialize state: stop snapclient if BT is not connected at startup
if bluetoothctl info "\$MAC" 2>/dev/null | grep -q 'Connected: yes'; then
    WAS_CONNECTED=true
else
    systemctl stop snapclient 2>/dev/null || true
fi
while true; do
    if bluetoothctl info "\$MAC" 2>/dev/null | grep -q 'Connected: yes'; then
        if [ "\$WAS_CONNECTED" = false ]; then
            # Just reconnected — switch to SBC-XQ and start snapclient
            sleep 2
            DEV_ID=\$(su - ${JUKEBOX_USER} -c "\$PW_ENV pw-cli list-objects 2>/dev/null" | grep -B20 "\$CARD" | grep "^.id " | tail -1 | awk '{print \$2}' | tr -d ',')
            if [ -n "\$DEV_ID" ]; then
                su - ${JUKEBOX_USER} -c "\$PW_ENV wpctl set-profile \$DEV_ID 131074" 2>/dev/null
                for i in \$(seq 1 10); do
                    sleep 1
                    if su - ${JUKEBOX_USER} -c "\$PW_ENV wpctl status 2>/dev/null" | grep -q "vol:"; then
                        break
                    fi
                done
            fi
            sleep 2
            systemctl start snapclient
            WAS_CONNECTED=true
        fi
    else
        # Not connected — stop snapclient so MA pauses, then try reconnect
        if [ "\$WAS_CONNECTED" = true ]; then
            systemctl stop snapclient
            WAS_CONNECTED=false
        fi
        bluetoothctl connect "\$MAC" 2>/dev/null || true
    fi
    sleep 15
done
WATCHDOG
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

echo "==> Installing Flask and websocket-client for web dashboard"
apt-get install -y -qq python3-flask python3-websocket

echo "==> Deploying web dashboard"
mkdir -p /opt/jukebox/templates
cp -r "${SCRIPT_DIR}/web/app.py" /opt/jukebox/
cp -r "${SCRIPT_DIR}/web/cava.conf" /opt/jukebox/
cp -r "${SCRIPT_DIR}/web/templates/" /opt/jukebox/templates/

cat > /etc/systemd/system/jukebox-web.service << EOF
[Unit]
Description=Jukebox Pi Web Dashboard
After=network.target pipewire.service

[Service]
User=${JUKEBOX_USER}
Group=${JUKEBOX_USER}
WorkingDirectory=/opt/jukebox
Environment=XDG_RUNTIME_DIR=/run/user/${UID_NUM}
Environment=SNAPCAST_SERVER=${SNAPCAST_SERVER}
Environment=MA_TOKEN=${MA_TOKEN}
ExecStart=/usr/bin/python3 /opt/jukebox/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable snapclient bt-autoconnect bluetooth wifi-roam jukebox-web

echo "==> Disabling unnecessary timers"
systemctl disable --now \
    apt-daily.timer \
    apt-daily-upgrade.timer \
    man-db.timer \
    fstrim.timer \
    e2scrub_all.timer \
    2>/dev/null || true

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Reboot: sudo reboot"
echo "  2. Put ${BT_DEVICE_NAME} in Bluetooth pairing mode"
echo "  3. Run: sudo ./pair-bt.sh"
echo ""
