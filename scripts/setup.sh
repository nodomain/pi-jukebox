#!/usr/bin/env bash
# Jukebox Pi Setup Script
# Provisions a fresh Raspberry Pi OS Lite (64-bit) as a Snapcast client
# with Bluetooth A2DP output.
#
# Idempotent — safe to run multiple times.
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

UID_NUM=$(id -u "${JUKEBOX_USER}")
CARD_NAME="bluez_card.${BT_MAC//:/_}"

# --- Helper ---
ensure_file() {
    # Write content to file only if it differs. Usage: ensure_file <path> <content>
    local path="$1" content="$2"
    mkdir -p "$(dirname "$path")"
    if [[ ! -f "$path" ]] || [[ "$(cat "$path")" != "$content" ]]; then
        printf '%s\n' "$content" > "$path"
        echo "  updated $path"
        return 0  # changed
    fi
    return 1  # unchanged
}

# --- Sudoers ---
echo "==> Passwordless sudo"
SUDOERS_LINE="${JUKEBOX_USER} ALL=(ALL) NOPASSWD: ALL"
SUDOERS_FILE="/etc/sudoers.d/${JUKEBOX_USER}"
if [[ ! -f "$SUDOERS_FILE" ]] || ! grep -qF "$SUDOERS_LINE" "$SUDOERS_FILE"; then
    echo "$SUDOERS_LINE" > "$SUDOERS_FILE"
    chmod 440 "$SUDOERS_FILE"
    echo "  configured"
else
    echo "  already configured"
fi

# --- User groups ---
echo "==> Bluetooth group"
if id -nG "${JUKEBOX_USER}" | grep -qw bluetooth; then
    echo "  already in group"
else
    usermod -aG bluetooth "${JUKEBOX_USER}"
    echo "  added"
fi

# --- User linger ---
echo "==> User linger"
if [[ -f "/var/lib/systemd/linger/${JUKEBOX_USER}" ]]; then
    echo "  already enabled"
else
    loginctl enable-linger "${JUKEBOX_USER}"
    echo "  enabled"
fi

# --- Packages ---
echo "==> Packages"
PACKAGES=(snapclient bluez pipewire pipewire-pulse wireplumber
    libspa-0.2-bluetooth pulseaudio-utils rfkill cava
    python3-flask python3-websocket)
MISSING=()
for pkg in "${PACKAGES[@]}"; do
    if ! dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
        MISSING+=("$pkg")
    fi
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
    apt-get update -qq
    apt-get install -y -qq "${MISSING[@]}"
    echo "  installed: ${MISSING[*]}"
else
    echo "  all installed"
fi

# --- Snapclient config ---
echo "==> Snapclient"
ensure_file /etc/default/snapclient \
    "SNAPCLIENT_OPTS=\"--host ${SNAPCAST_SERVER} --player pulse --latency 100\"" || true

mkdir -p /etc/systemd/system/snapclient.service.d
ensure_file /etc/systemd/system/snapclient.service.d/override.conf \
"[Service]
User=${JUKEBOX_USER}
Group=${JUKEBOX_USER}
Environment=PULSE_RUNTIME_PATH=/run/user/${UID_NUM}/pulse" || true

# --- Bluetooth ---
echo "==> Bluetooth auto-enable"
if grep -q '^AutoEnable=true' /etc/bluetooth/main.conf 2>/dev/null; then
    echo "  already enabled"
else
    sed -i 's/^#AutoEnable.*/AutoEnable=true/' /etc/bluetooth/main.conf
    sed -i 's/^AutoEnable=false/AutoEnable=true/' /etc/bluetooth/main.conf
    echo "  enabled"
fi

# --- WiFi power save ---
echo "==> WiFi power save"
ensure_file /etc/NetworkManager/conf.d/wifi-powersave.conf \
"[connection]
wifi.powersave = 2" || true

# --- WiFi roaming ---
echo "==> WiFi roaming helper"
cat > /usr/local/bin/wifi-roam << 'ROAM'
#!/usr/bin/env bash
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

ensure_file /etc/systemd/system/wifi-roam.service \
"[Unit]
Description=WiFi roaming helper
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
ExecStart=/usr/local/bin/wifi-roam
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target" || true

# --- WirePlumber ---
echo "==> WirePlumber headless fix + SBC-XQ"
ensure_file /etc/wireplumber/wireplumber.conf.d/50-bluez-no-seat.conf \
'wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}' || true

ensure_file /etc/wireplumber/wireplumber.conf.d/51-bluez-sbc-xq.conf \
'monitor.bluez.rules = [
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
]' || true

# --- SD card protection ---
echo "==> SD card writes"
# Only rewrite fstab if tmpfs mounts are missing
if ! grep -q 'tmpfs.*/var/log' /etc/fstab 2>/dev/null; then
    FSTAB_ROOT=$(grep 'PARTUUID.*/ ' /etc/fstab || grep 'PARTUUID.*/[[:space:]]' /etc/fstab | head -1)
    ROOT_UUID=$(echo "$FSTAB_ROOT" | awk '{print $1}')
    BOOT_UUID=$(grep 'boot/firmware' /etc/fstab | awk '{print $1}')
    cat > /etc/fstab << EOF
proc            /proc           proc    defaults          0       0
${BOOT_UUID}  /boot/firmware  vfat    defaults          0       2
${ROOT_UUID}  /               ext4    defaults,noatime,commit=120  0       1
tmpfs           /var/log        tmpfs   defaults,noatime,nosuid,nodev,noexec,size=20m  0  0
tmpfs           /var/tmp        tmpfs   defaults,noatime,nosuid,nodev,size=20m  0  0
EOF
    echo "  fstab updated"
else
    echo "  fstab already has tmpfs"
fi

ensure_file /etc/systemd/journald.conf.d/volatile.conf \
"[Journal]
Storage=volatile
RuntimeMaxUse=10M" || true

# --- Bluetooth watchdog ---
echo "==> Bluetooth watchdog"
cat > /usr/local/bin/bt-watchdog << WATCHDOG
#!/usr/bin/env bash
MAC="${BT_MAC}"
CARD="${CARD_NAME}"
PW_ENV="XDG_RUNTIME_DIR=/run/user/${UID_NUM}"
WAS_CONNECTED=false

switch_codec() {
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
}

wait_for_sink() {
    # Wait until the BT sink is the default PipeWire sink (up to 15s)
    for i in \$(seq 1 15); do
        if su - ${JUKEBOX_USER} -c "\$PW_ENV wpctl status 2>/dev/null" | grep -A1 'Audio/Sink' | grep -qi 'bluez\|${BT_MAC//:/_}'; then
            return 0
        fi
        sleep 1
    done
    return 1
}

sleep 10
# Initialize state: sync snapclient with BT connection
if bluetoothctl info "\$MAC" 2>/dev/null | grep -q 'Connected: yes'; then
    WAS_CONNECTED=true
    switch_codec
    wait_for_sink
    systemctl is-active --quiet snapclient || systemctl start snapclient
else
    systemctl stop snapclient 2>/dev/null || true
fi
while true; do
    if bluetoothctl info "\$MAC" 2>/dev/null | grep -q 'Connected: yes'; then
        if [ "\$WAS_CONNECTED" = false ]; then
            sleep 2
            switch_codec
            wait_for_sink
            systemctl start snapclient
            WAS_CONNECTED=true
        fi
    else
        if [ "\$WAS_CONNECTED" = true ]; then
            systemctl stop snapclient
            WAS_CONNECTED=false
        fi
        bluetoothctl connect "\$MAC" 2>/dev/null || true
    fi
    sleep 5
done
WATCHDOG
chmod +x /usr/local/bin/bt-watchdog

ensure_file /etc/systemd/system/bt-autoconnect.service \
"[Unit]
Description=Auto-connect to ${BT_DEVICE_NAME} via Bluetooth
After=bluetooth.service
Wants=bluetooth.service

[Service]
ExecStart=/usr/local/bin/bt-watchdog
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target" || true

# --- Web dashboard ---
echo "==> Web dashboard"
WEB_SRC="${SCRIPT_DIR}/../web"
mkdir -p /opt/jukebox/templates /opt/jukebox/static /opt/jukebox/routes
if [[ -d "$WEB_SRC" ]]; then
    cp "${WEB_SRC}/app.py" /opt/jukebox/app.py
    cp "${WEB_SRC}/helpers.py" /opt/jukebox/helpers.py
    cp "${WEB_SRC}/cava.conf" /opt/jukebox/cava.conf
    cp "${WEB_SRC}"/routes/*.py /opt/jukebox/routes/
    cp "${WEB_SRC}"/static/style.css /opt/jukebox/static/
    cp "${WEB_SRC}"/static/app.js /opt/jukebox/static/
    cp "${WEB_SRC}"/static/manifest.json /opt/jukebox/static/ 2>/dev/null || true
    cp "${WEB_SRC}"/static/favicon.svg /opt/jukebox/static/ 2>/dev/null || true
    cp "${WEB_SRC}"/static/icon-*.png /opt/jukebox/static/ 2>/dev/null || true
    cp "${WEB_SRC}/templates/index.html" /opt/jukebox/templates/index.html
    echo "  files copied"
else
    echo "  web/ not found, skipping (use 'make deploy' instead)"
fi

ensure_file /etc/systemd/system/jukebox-web.service \
"[Unit]
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
WantedBy=multi-user.target" || true

# --- Enable services ---
echo "==> Enabling services"
systemctl daemon-reload
SERVICES=(snapclient bt-autoconnect bluetooth wifi-roam jukebox-web)
for svc in "${SERVICES[@]}"; do
    if systemctl is-enabled "$svc" &>/dev/null; then
        echo "  $svc already enabled"
    else
        systemctl enable "$svc"
        echo "  $svc enabled"
    fi
done

# --- Disable unnecessary timers ---
echo "==> Disabling unnecessary timers"
TIMERS=(apt-daily.timer apt-daily-upgrade.timer man-db.timer fstrim.timer e2scrub_all.timer)
for timer in "${TIMERS[@]}"; do
    if systemctl is-enabled "$timer" &>/dev/null; then
        systemctl disable --now "$timer" 2>/dev/null || true
        echo "  $timer disabled"
    fi
done

echo ""
echo "=== Setup complete ==="
echo "Next steps:"
echo "  1. Reboot: sudo reboot"
echo "  2. Put ${BT_DEVICE_NAME} in Bluetooth pairing mode"
echo "  3. Run: sudo ./pair-bt.sh"
echo ""
