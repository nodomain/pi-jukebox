# Jukebox Pi

Raspberry Pi Zero 2 W as a headless [Snapcast](https://github.com/badaix/snapcast) client, streaming audio from [Music Assistant](https://music-assistant.io/) to a Bluetooth speaker via A2DP.

Designed for battery/portable use — tmpfs mounts and volatile journal eliminate SD card writes during normal operation. Safe to pull power.

## Features

- Snapcast client with PipeWire/PulseAudio Bluetooth output
- SBC-XQ codec for better audio quality over Bluetooth
- Auto-connects to paired Bluetooth speaker on boot and reconnects when speaker is power-cycled
- Zero SD card writes during normal operation (tmpfs + volatile journal)
- WiFi roaming helper — auto-rescans when signal drops below -70 dBm
- Web dashboard at `http://<host>:5000` — Now Playing, playback controls, live system charts, BT/service management
- Fully reproducible setup via two scripts

## Architecture

```
Music Assistant (Home Assistant Add-on)
    ↓ TCP stream (FLAC 48kHz/16bit/Stereo)
Snapcast Server
    ↓ network
Snapcast Client (this Pi)
    ↓ PulseAudio (PipeWire)
Bluetooth A2DP (SBC-XQ)
    ↓ wireless
Bluetooth Speaker
```

## Prerequisites

- Raspberry Pi Zero 2 W (or any Pi with Bluetooth)
- Raspberry Pi OS Lite (64-bit, Debian Trixie)
- Snapcast server running (e.g. Music Assistant add-on in Home Assistant)
- Bluetooth speaker with A2DP support

## Setup

### 1. Flash SD card

Use Raspberry Pi Imager with these settings:
- OS: Raspberry Pi OS Lite (64-bit)
- Hostname: your choice (e.g. `jukebox`)
- Username and password
- Enable SSH
- Configure WiFi

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your values:
#   JUKEBOX_USER    - the username you set in Pi Imager
#   JUKEBOX_HOST    - hostname.local
#   SNAPCAST_SERVER - IP of your Snapcast/Home Assistant server
#   BT_MAC          - Bluetooth MAC of your speaker
#   BT_DEVICE_NAME  - friendly name of your speaker
```

### 3. Install

```bash
scp .env setup.sh pair-bt.sh <user>@<host>:~
ssh <user>@<host> "chmod +x setup.sh pair-bt.sh && sudo ./setup.sh"
```

The Pi will reboot after setup.

### 4. Pair speaker

Put your Bluetooth speaker in pairing mode, then:

```bash
ssh <user>@<host> "sudo ./pair-bt.sh && sudo reboot"
```

After reboot, the Pi auto-connects and starts streaming. Done.

## What Gets Configured

| Component | Details |
|---|---|
| sudoers | Passwordless sudo for `JUKEBOX_USER` |
| user groups | `JUKEBOX_USER` added to `bluetooth` group |
| user linger | Enabled for `JUKEBOX_USER` (PipeWire runs without login) |
| python3-flask | Installed for web dashboard |
| snapclient | PulseAudio output, connects to Snapcast server |
| PipeWire + WirePlumber | Bluetooth A2DP audio backend |
| bluez | `AutoEnable=true`, speaker paired and trusted |
| WirePlumber | Seat monitoring disabled (headless fix), SBC-XQ codec preferred |
| bt-autoconnect.service | Watchdog — checks BT every 15s, reconnects and switches to SBC-XQ codec |
| wifi-roam.service | Checks WiFi signal every 30s, triggers rescan if below -70 dBm |
| jukebox-web.service | Flask web dashboard on port 5000 — Now Playing, controls, live charts |
| SD card protection | tmpfs on /var/log + /var/tmp, volatile journal, ext4 commit=120s |
| WiFi power save | Disabled — prevents latency spikes during audio streaming |
| Disabled timers | apt-daily, man-db, fstrim, e2scrub (reduce SD writes) |

### Key files on the Pi

| Path | Purpose |
|---|---|
| `/etc/sudoers.d/<user>` | Passwordless sudo |
| `/etc/default/snapclient` | Snapcast server + player config |
| `/etc/systemd/system/snapclient.service.d/override.conf` | Run snapclient as user (for PulseAudio access) |
| `/etc/systemd/system/bt-autoconnect.service` | Bluetooth watchdog service |
| `/usr/local/bin/bt-watchdog` | Monitors BT, reconnects, switches to SBC-XQ, restarts snapclient |
| `/etc/wireplumber/wireplumber.conf.d/50-bluez-no-seat.conf` | Headless Bluetooth fix |
| `/etc/wireplumber/wireplumber.conf.d/51-bluez-sbc-xq.conf` | Prefer SBC-XQ codec over SBC |
| `/etc/bluetooth/main.conf` | Bluetooth auto-enable |
| `/etc/NetworkManager/conf.d/wifi-powersave.conf` | WiFi power save disabled |
| `/usr/local/bin/wifi-roam` | WiFi roaming helper — rescans on weak signal |
| `/etc/systemd/system/wifi-roam.service` | WiFi roaming service |
| `/opt/jukebox/app.py` | Web dashboard Flask app |
| `/opt/jukebox/templates/index.html` | Web dashboard HTML template |
| `/etc/systemd/system/jukebox-web.service` | Web dashboard service |
| `/etc/systemd/journald.conf.d/volatile.conf` | Journal in RAM only |

## Music Assistant Settings

Recommended player settings in Music Assistant (Settings → Players → your player):

| Setting | Value | Why |
|---|---|---|
| Volume normalization | ✅ enabled | Consistent volume across tracks |
| Clipping limiter | ✅ enabled | Prevents distortion |
| Normalization target | **-14 LUFS** | Default -17 is too quiet for Bluetooth + party speaker. -14 is louder while the limiter prevents clipping |
| Smart Fades | ✅ Standard Crossfade | Intelligently crossfades between tracks — detects fade-outs and hard endings |
| Crossfade | 8s | Fallback duration when Smart Fades can't determine the optimal transition |

## Web Dashboard

After setup, the dashboard is available at `http://<host>:5000`.

**Features:**
- **Now Playing** — album art, track, artist, album from Snapcast metadata
- **Playback Controls** — play/pause toggle, skip next/previous via Snapcast JSON-RPC
- **Volume Slider** — controls PipeWire default sink volume
- **Status Cards** — Bluetooth connection/codec, CPU temp, CPU frequency, WiFi signal
- **System Health** — memory, load, uptime, SD writes, throttle status decoded
- **Live Charts** — Temp & Mem, CPU MHz, WiFi Signal, System Load, Traffic, SD Writes
- **Snapcast Clients** — stream status, client volume/latency chart
- **Bluetooth Controls** — scan, connect, disconnect
- **Service Controls** — restart snapclient, restart BT watchdog, reboot

The dashboard is mobile-first (responsive up to 1200px) with a dark theme.

To redeploy after changes:
```bash
scp -r web/ <user>@<host>:~/web
ssh <user>@<host> "sudo cp -r ~/web/* /opt/jukebox/ && sudo systemctl restart jukebox-web"
```

## Troubleshooting

### No audio after boot

```bash
# Check Bluetooth connection
ssh <user>@<host> "sudo bluetoothctl info <BT_MAC> | grep Connected"

# If disconnected, the watchdog should reconnect within 15s.
# To force it:
ssh <user>@<host> "sudo bluetoothctl connect <BT_MAC> && sudo systemctl restart snapclient"
```

### Check audio pipeline

```bash
ssh <user>@<host> "wpctl status"
```

Look for your speaker under Sinks and Snapcast stream with `[active]`.

### Check codec

```bash
ssh <user>@<host> "pw-dump 2>&1 | grep api.bluez5.codec"
```

Should show `sbc_xq`. If it shows `sbc`, the watchdog will switch on next reconnect.

### Check service logs

```bash
ssh <user>@<host> "sudo journalctl -u snapclient --no-pager -n 20"
ssh <user>@<host> "sudo journalctl -u bt-autoconnect --no-pager -n 20"
```

### WirePlumber doesn't see Bluetooth

The most common issue on headless Pi. Verify the seat monitoring fix is in place:

```bash
ssh <user>@<host> "cat /etc/wireplumber/wireplumber.conf.d/50-bluez-no-seat.conf"
```

Should contain `monitor.bluez.seat-monitoring = disabled` inside `wireplumber.profiles.main`.

### Verify SD card writes

```bash
# Take two readings 30s apart — write count (field 8) should not increase
ssh <user>@<host> "cat /proc/diskstats | grep mmcblk0 | head -1; sleep 30; cat /proc/diskstats | grep mmcblk0 | head -1"
```

## Release

2026-04-19
