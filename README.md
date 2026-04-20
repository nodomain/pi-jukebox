# 🎵 Jukebox Pi

Raspberry Pi Zero 2 W as a headless [Snapcast](https://github.com/badaix/snapcast) client, streaming audio from [Music Assistant](https://music-assistant.io/) to a Bluetooth speaker via A2DP.

Designed for battery/portable use — safe to pull power at any time.

## Features

- **Snapcast → Bluetooth** — streams from Music Assistant via PipeWire to any A2DP speaker
- **SBC-XQ codec** — better audio quality over Bluetooth (auto-negotiated)
- **Auto-reconnect** — watchdog reconnects to speaker on boot or power-cycle
- **Zero SD card writes** — tmpfs mounts + volatile journal during normal operation
- **WiFi roaming** — auto-rescans when signal drops below -70 dBm
- **Web dashboard** — Now Playing, playback controls, queue browser, live system charts, BT/service management
- **Fully reproducible** — two scripts to go from fresh Pi OS to streaming

## Architecture

```
Music Assistant (Home Assistant Add-on)
    ↓ TCP stream (FLAC 48 kHz / 16 bit / Stereo)
Snapcast Server
    ↓ network
Snapcast Client (this Pi)
    ↓ PipeWire / PulseAudio
Bluetooth A2DP (SBC-XQ)
    ↓ wireless
Bluetooth Speaker
```

## Web Dashboard

Available at `http://<hostname>:5000` after setup. Mobile-first, dark theme.

- **Now Playing** — album art with blurred background, track info, progress bar, lyrics
- **Playback Controls** — play/pause, skip, shuffle, repeat via Snapcast JSON-RPC
- **FFT Visualizer** — real-time audio visualization via cava
- **Queue Browser** — reorder, delete, jump to track, clear
- **Volume Control** — PipeWire default sink
- **System Diagnostics** — CPU temp/freq, memory, WiFi signal, SD writes, throttle flags
- **Live Charts** — Chart.js graphs for temp, CPU, WiFi, load, traffic, SD writes, Snapcast buffer jitter
- **Bluetooth Management** — scan, connect, disconnect
- **Service Controls** — restart snapclient, BT watchdog, reboot

## Prerequisites

- Raspberry Pi Zero 2 W (or any Pi with Bluetooth)
- Raspberry Pi OS Lite (64-bit, Debian Trixie)
- Snapcast server (e.g. Music Assistant add-on in Home Assistant)
- Bluetooth speaker with A2DP support

## Quick Start

### 1. Flash SD card

Use Raspberry Pi Imager:
- **OS:** Raspberry Pi OS Lite (64-bit)
- Set hostname, username/password, SSH, WiFi

### 2. Configure

```bash
cp .env.example .env
# Edit .env — see .env.example for all variables
```

### 3. Install

```bash
scp .env scripts/setup.sh scripts/pair-bt.sh <user>@<host>:~
ssh <user>@<host> "chmod +x setup.sh pair-bt.sh && sudo ./setup.sh"
```

The Pi reboots after setup.

### 4. Pair speaker

Put your speaker in pairing mode, then:

```bash
ssh <user>@<host> "sudo ./pair-bt.sh && sudo reboot"
```

After reboot the Pi auto-connects and starts streaming.

### 5. Deploy dashboard updates

```bash
make deploy
```

## Make Targets

```
make help      — show all targets
make deploy    — deploy web dashboard to the Pi
make setup     — copy scripts to Pi and run setup.sh
make pair      — run pair-bt.sh on the Pi
make status    — show service + BT + Snapcast status
make logs      — tail service logs
make restart   — restart all jukebox services
make reboot    — reboot the Pi
make ssh       — open SSH session
```

## What Gets Configured

`setup.sh` provisions everything from a fresh Pi OS install:

| Component | Details |
|---|---|
| **snapclient** | PulseAudio output, connects to Snapcast server |
| **PipeWire + WirePlumber** | Bluetooth A2DP audio backend |
| **BlueZ** | `AutoEnable=true`, speaker paired and trusted |
| **WirePlumber** | Seat monitoring disabled (headless fix), SBC-XQ codec preferred |
| **bt-autoconnect.service** | Watchdog — reconnects BT every 15 s, switches to SBC-XQ |
| **wifi-roam.service** | Rescans WiFi every 30 s if signal < -70 dBm |
| **jukebox-web.service** | Flask dashboard on port 5000 |
| **cava** | FFT audio visualizer for the dashboard |
| **SD card protection** | tmpfs on `/var/log` + `/var/tmp`, volatile journal, `commit=120s` |
| **WiFi power save** | Disabled — prevents latency spikes |
| **Disabled timers** | apt-daily, man-db, fstrim, e2scrub |

## Project Structure

```
.
├── .env.example              # Environment variable template
├── Makefile                  # Dev machine targets (deploy, setup, logs, status, ...)
├── scripts/
│   ├── setup.sh              # Pi provisioning — idempotent (run on Pi as root)
│   └── pair-bt.sh            # Bluetooth pairing (run on Pi as root)
└── web/                      # Flask dashboard (deployed to /opt/jukebox/)
    ├── app.py                # All API routes, SSE endpoints, MA WebSocket relay
    ├── cava.conf             # cava config (48 bars, PipeWire input, ASCII output)
    └── templates/
        └── index.html        # Single-page app — HTML, CSS, JS all inline
```

## Music Assistant Settings

### Snapcast Provider

| Setting | Value | Why |
|---|---|---|
| Buffer size | 1500 ms | Compensates WiFi/BT jitter (default 1000) |
| Chunk size | 40 ms | Less overhead, fewer timing issues (default 26) |
| Transport codec | FLAC | Lossless transport, decoded on the Pi |

### Player

| Setting | Value | Why |
|---|---|---|
| Volume normalization | ✅ | Consistent volume across tracks |
| Clipping limiter | ✅ | Prevents distortion |
| Normalization target | -14 LUFS | Louder than default -17 for BT speakers |
| Smart Fades | Standard Crossfade | Intelligent transitions between tracks |

## Troubleshooting

<details>
<summary>No audio after boot</summary>

```bash
# Check Bluetooth connection
ssh <user>@<host> "bluetoothctl info <BT_MAC> | grep Connected"

# Force reconnect
ssh <user>@<host> "bluetoothctl connect <BT_MAC> && sudo systemctl restart snapclient"
```

The watchdog should auto-reconnect within 15 seconds.
</details>

<details>
<summary>Check audio pipeline</summary>

```bash
ssh <user>@<host> "wpctl status"
```

Look for your speaker under Sinks with `[active]`.
</details>

<details>
<summary>Check Bluetooth codec</summary>

```bash
ssh <user>@<host> "pw-dump 2>&1 | grep api.bluez5.codec"
```

Should show `sbc_xq`. If it shows `sbc`, the watchdog will switch on next reconnect.
</details>

<details>
<summary>WirePlumber doesn't see Bluetooth</summary>

Most common issue on headless Pi. Verify the seat monitoring fix:

```bash
ssh <user>@<host> "cat /etc/wireplumber/wireplumber.conf.d/50-bluez-no-seat.conf"
```

Should contain `monitor.bluez.seat-monitoring = disabled`.
</details>

<details>
<summary>Verify zero SD card writes</summary>

```bash
# Two readings 30s apart — write count (field 8) should not increase
ssh <user>@<host> "cat /proc/diskstats | grep mmcblk0 | head -1; sleep 30; cat /proc/diskstats | grep mmcblk0 | head -1"
```
</details>

<details>
<summary>Service logs</summary>

```bash
ssh <user>@<host> "journalctl -u snapclient --no-pager -n 20"
ssh <user>@<host> "journalctl -u bt-autoconnect --no-pager -n 20"
ssh <user>@<host> "journalctl -u jukebox-web --no-pager -n 20"
```
</details>

### Performance Notes

Buffer warnings in snapclient logs (`pShortBuffer`, `pBuffer`, `pMiniBuffer`) are normal — Snapcast compensates internally. As long as there are no audible glitches, these are cosmetic.

ALSA output is not an option because PipeWire is required for Bluetooth A2DP routing. The `--player pulse` flag works because PipeWire provides PulseAudio compatibility.

## License

[MIT](LICENSE)
