# Jukebox Pi

Raspberry Pi Zero 2 W as a headless [Snapcast](https://github.com/badaix/snapcast) client, streaming audio from [Music Assistant](https://music-assistant.io/) to a Bluetooth speaker via A2DP.

Designed for battery/portable use — overlay filesystem protects the SD card from corruption on hard power-off.

## Features

- Snapcast client with PipeWire/PulseAudio Bluetooth output
- Auto-connects to paired Bluetooth speaker on boot (retries until speaker is available)
- Read-only root filesystem (overlay FS) — safe to pull power at any time
- Fully reproducible setup via two scripts

## Architecture

```
Music Assistant (Home Assistant Add-on)
    ↓ TCP stream (FLAC 48kHz/16bit/Stereo)
Snapcast Server
    ↓ network
Snapcast Client (this Pi)
    ↓ PulseAudio (PipeWire)
Bluetooth A2DP
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
ssh <user>@<host> "sudo ./pair-bt.sh"
```

This pairs the speaker, enables overlay FS, and reboots. Done.

## What Gets Configured

| Component | Details |
|---|---|
| snapclient | PulseAudio output, connects to Snapcast server |
| PipeWire + WirePlumber | Bluetooth A2DP audio backend |
| bluez | `AutoEnable=true`, speaker paired and trusted |
| WirePlumber | Seat monitoring disabled (headless fix) |
| bt-autoconnect.service | Retries BT connection every 15s, restarts snapclient on success |
| Overlay FS | Root + boot read-only, all writes go to RAM |
| Disabled timers | apt-daily, man-db, fstrim, e2scrub (reduce SD writes) |

### Key files on the Pi

| Path | Purpose |
|---|---|
| `/etc/default/snapclient` | Snapcast server + player config |
| `/etc/systemd/system/snapclient.service.d/override.conf` | Run snapclient as user (for PulseAudio access) |
| `/etc/systemd/system/bt-autoconnect.service` | Auto-connect + snapclient restart |
| `/etc/wireplumber/wireplumber.conf.d/50-bluez-no-seat.conf` | Headless Bluetooth fix |
| `/etc/bluetooth/main.conf` | Bluetooth auto-enable |

## Making Changes

With overlay FS active, all changes are lost on reboot. To persist changes:

```bash
# Disable overlay (needs two reboots due to read-only boot partition)
ssh <user>@<host> "sudo mount -o remount,rw /boot/firmware; sudo raspi-config nonint disable_overlayfs; sudo raspi-config nonint disable_bootro; sudo reboot"

# Make your changes...

# Re-enable overlay
ssh <user>@<host> "sudo raspi-config nonint enable_overlayfs; sudo raspi-config nonint enable_bootro; sudo reboot"
```

## Troubleshooting

### No audio after boot

```bash
# Check Bluetooth connection
ssh <user>@<host> "sudo bluetoothctl info <BT_MAC> | grep Connected"

# If disconnected, reconnect + restart snapclient
ssh <user>@<host> "sudo bluetoothctl connect <BT_MAC> && sudo systemctl restart snapclient"
```

### Check audio pipeline

```bash
ssh <user>@<host> "wpctl status"
```

Look for your speaker under Sinks and Snapcast stream with `[active]`.

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

## Release

2026-04-19
