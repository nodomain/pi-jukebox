# 🎵 Jukebox Pi

Raspberry Pi Zero 2 W as a headless [Snapcast](https://github.com/badaix/snapcast) client, streaming audio from [Music Assistant](https://music-assistant.io/) to a Bluetooth speaker via A2DP.

Designed for battery/portable use — safe to pull power at any time.

## Features

- **Snapcast → Bluetooth** — streams from Music Assistant via PipeWire to any A2DP speaker
- **AirPlay** — `shairport-sync` receiver, shows up as "Jukebox" on your iPhone
- **Spotify Connect** — `raspotify` (librespot) receiver, shows up as "Jukebox" in Spotify (Premium required)
- **SBC-XQ codec** — better audio quality over Bluetooth (auto-negotiated)
- **Auto-reconnect** — watchdog reconnects to speaker on boot or power-cycle
- **Zero SD card writes** — tmpfs mounts + volatile journal during normal operation
- **WiFi roaming** — auto-rescans when signal drops below -70 dBm
- **Web dashboard** — Now Playing, playback controls, queue browser, live system charts, BT/service management
- **AI recommendations** — hybrid Last.fm + LLM suggestions, mood-aware, validated against your library
- **Last.fm scrobbling** — auto-scrobbles played tracks to build your listening profile
- **Fully reproducible** — two scripts to go from fresh Pi OS to streaming

## Architecture

```
                ┌─ Music Assistant ─→ Snapcast Server ─┐
iPhone                                                  ↓
  ↓ AirPlay                                      Snapcast Client
shairport-sync ─────────────────────────────→ PipeWire / PulseAudio
                                                        ↑
Spotify App                                             │
  ↓ Spotify Connect                                     │
raspotify (librespot) ─────────────────────────────────┘
                                                        ↓
                                              Bluetooth A2DP (SBC-XQ)
                                                        ↓
                                                 Bluetooth Speaker
```

Three audio sources share the same Bluetooth output. When AirPlay or Spotify
starts, Snapcast is paused automatically; when they end, Snapcast resumes.

## Web Dashboard

Available at `http://<hostname>:8080` after setup. Mobile-first, dark theme.

- **Now Playing** — album art with blurred background, title/artist/album, progress bar, lyrics
- **AirPlay Now Playing** — shows track info and cover art from the iPhone when AirPlay is active
- **Spotify Now Playing** — shows track info and cover art (via oEmbed) when Spotify Connect is active
- **Playback Controls** — play/pause, skip, shuffle, repeat, favorite, sleep timer
- **FFT Visualizer** — real-time audio visualization via cava
- **Queue Browser** — reorder, delete, jump to track, clear (auto-expands when tracks are queued)
- **Music Search** — search MA library for tracks, albums, playlists with provider icons, expand albums/playlists to play individual tracks
- **Recently Played** — quick access to recent tracks
- **Playlists** — browse and play MA library playlists
- **Three Volume Sliders** — Music Assistant, Snapcast client, PipeWire sink
- **System Diagnostics** — CPU temp/freq, memory, WiFi signal, SD writes, throttle flags (collapsible)
- **Live Charts** — Chart.js graphs for temp, CPU, WiFi, load, traffic, SD writes, Snapcast buffer jitter
- **Bluetooth Management** — scan, connect, disconnect
- **Service Controls** — restart snapclient, BT watchdog, reboot
- **AI Recommendations** — Last.fm similar tracks curated by LLM, integrated in search with ✨ AI chip
- **Last.fm Scrobbling** — via MA plugin, auto-scrobbles all played tracks
- **Synced Lyrics** — LRCLIB integration, highlighted current line with auto-scroll
- **"Don't Stop the Music"** — ∞ button, uses MA native feature to auto-fill queue
- **Theme Toggle** — dark/light mode

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

### 6. USB WiFi adapter (optional, recommended)

For stable audio streaming, plug in a TP-Link AC600 (Archer T2U Nano) USB WiFi adapter. It connects on 5 GHz, freeing the 2.4 GHz band for Bluetooth and reducing audio stutter. When the USB adapter is present, onboard WiFi is automatically disabled to prevent dual-homing routing issues.

```bash
# Build and install the driver (requires Docker on the dev machine)
./scripts/build-wifi-driver.sh

# Re-run setup to configure NetworkManager, USB stability, CPU governor
make setup
```

Setup configures:
- **USB autosuspend disabled** — prevents the Pi's USB controller from dropping the adapter
- **dwc_otg kernel params** — stabilizes the Pi Zero 2 W's single USB port under load
- **Onboard WiFi auto-disabled** — udev rule disconnects wlan1 when wlan-usb is present
- **Automatic fallback** — if the USB adapter is unplugged, onboard WiFi reconnects

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
| **snapclient** | PulseAudio output, connects to Snapcast server, 500ms latency buffer, fixed hostID |
| **PipeWire + WirePlumber** | Bluetooth A2DP audio backend |
| **BlueZ** | `AutoEnable=true`, speaker paired and trusted |
| **WirePlumber** | Seat monitoring disabled (headless fix), SBC-XQ codec preferred |
| **bt-autoconnect.service** | Watchdog — reconnects BT every 5 s, switches to SBC-XQ, pauses on AirPlay |
| **wifi-roam.service** | Rescans WiFi every 30 s if signal < -70 dBm |
| **jukebox-web.service** | Flask dashboard on port 8080 |
| **shairport-sync** | AirPlay receiver — pauses Snapcast while iPhone streams |
| **raspotify** | Spotify Connect receiver — pauses Snapcast while Spotify streams |
| **avahi-daemon** | mDNS for AirPlay/Spotify discovery |
| **cava** | FFT audio visualizer for the dashboard |
| **SD card protection** | tmpfs on `/var/log` + `/var/tmp`, volatile journal, `commit=120s` |
| **WiFi power save** | Disabled — prevents latency spikes |
| **USB WiFi (optional)** | udev rule + NM connection for TP-Link AC600, 5 GHz preferred, auto-fallback to onboard |
| **USB autosuspend** | Disabled via udev rule + kernel param `usbcore.autosuspend=-1` |
| **dwc_otg stability** | Kernel param `dwc_otg.fiq_fsm_mask=0x7` — stabilizes Pi Zero 2 W USB controller |
| **CPU governor** | Pinned to `performance` (1 GHz constant) — no clock-scaling delays for real-time audio |
| **WiFi exclusive mode** | Onboard WiFi auto-disabled when USB adapter present (prevents dual-homing) |
| **Disabled timers** | apt-daily, man-db, fstrim, e2scrub |

## Project Structure

```
.
├── .env.example              # Environment variable template
├── Makefile                  # Dev machine targets (deploy, setup, logs, status, ...)
├── scripts/
│   ├── setup.sh              # Pi provisioning — idempotent (run on Pi as root)
│   ├── pair-bt.sh            # Bluetooth pairing (run on Pi as root)
│   └── build-wifi-driver.sh  # Cross-compile RTL8812AU driver (run on dev machine)
└── web/                      # Flask dashboard (deployed to /opt/jukebox/)
    ├── app.py                # Flask app factory, blueprint registration
    ├── helpers.py            # Shared shell helpers (run, run_pw)
    ├── cava.conf             # cava config (48 bars, PipeWire input, ASCII output)
    ├── package.json          # esbuild for bundling JS modules
    ├── routes/               # Flask blueprints (one per concern)
    │   ├── ma.py             # Music Assistant API + WebSocket relay
    │   ├── snapcast.py       # Snapcast JSON-RPC + jitter log parser
    │   ├── audio.py          # PipeWire volume control
    │   ├── bluetooth.py      # BT scan/connect/disconnect
    │   ├── system.py         # System stats, service actions
    │   ├── fft.py            # cava FFT SSE stream
    │   ├── events.py         # Unified SSE endpoint
    │   └── airplay.py        # shairport-sync metadata reader
    ├── js/                   # ES modules, bundled to static/app.js
    │   ├── main.js           # Entry point
    │   ├── state.js          # Shared state
    │   ├── api.js            # Fetch wrappers
    │   ├── player.js         # Now playing, controls, volume, synced lyrics
    │   ├── queue.js          # Queue browser with optimistic UI
    │   ├── browse.js         # Search, AI recommendations, recently played, playlists
    │   ├── autoplay.js       # "Don't Stop the Music" toggle (MA native)
    │   ├── charts.js         # Chart.js setup
    │   ├── fft.js            # FFT visualizer
    │   ├── system.js         # BT, services
    │   ├── sse.js            # SSE connection
    │   └── theme.js          # Dark/light theme
    ├── static/               # Bundled app.js + CSS + icons
    └── templates/
        └── index.html        # Single-page app
```

## Music Assistant Settings

### Snapcast Provider

| Setting | Value | Why |
|---|---|---|
| Buffer size | 2000 ms | Compensates WiFi/BT jitter |
| Chunk size | 20 ms | Finer timing correction, less audible when Snapcast resyncs |
| Transport codec | FLAC | Lossless transport, decoded on the Pi |

### Player

| Setting | Value | Why |
|---|---|---|
| Volume normalization | ✅ | Consistent volume across tracks |
| Clipping limiter | ✅ | Prevents distortion |
| Normalization target | -14 LUFS | Louder than default -17 for BT speakers |
| Smart Fades | Standard Crossfade | Intelligent transitions between tracks |

## AI Recommendations

The dashboard includes an AI-powered recommendation feature that suggests similar tracks based on what's currently playing. It uses a hybrid approach:

1. **Last.fm** provides similar tracks and artists (collaborative filtering from millions of listeners)
2. **LLM** (via OpenRouter) curates the results, optionally filtered by a mood/vibe prompt
3. **Music Assistant** validates that each suggestion is actually playable in your library

### Setup

1. **Last.fm API Key** (free) — create one at https://www.last.fm/api/account/create
2. **OpenRouter API Key** — get one at https://openrouter.ai/keys

Add both to `.env`:

```bash
LASTFM_API_KEY=your_lastfm_api_key
LASTFM_SHARED_SECRET=your_lastfm_shared_secret
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=google/gemini-3.1-flash-lite   # optional, see model comparison below
```

### Last.fm Scrobbling

Scrobbling is handled by the [Music Assistant Last.fm plugin](https://www.music-assistant.io/plugins/lastfm_scrobble/), not by the Jukebox dashboard. Install it in MA under Settings → Plugins and configure your Last.fm credentials there. This scrobbles all tracks played through MA regardless of whether the dashboard is open.

The feature works in three modes:
- **Both keys** — full hybrid (Last.fm data + LLM curation). Best results.
- **Last.fm only** — returns raw similar tracks without LLM filtering. Still good.
- **OpenRouter only** — LLM generates recommendations from its own knowledge. Works but less reliable.

### OpenRouter Model Comparison

The task is simple: read ~20 track suggestions, pick the best 10, return JSON. Any model handles this, so optimize for speed and cost.

| Model | Cost (in/out per 1M) | Speed | Cost per request | Notes |
|---|---|---|---|---|
| **Gemini 3.1 Flash Lite** ⭐ | $0.25 / $1.50 | ⚡⚡⚡ | ~$0.0005 | Fastest, great JSON output. Default pick. |
| **Grok 4.1 Fast** | $0.20 / $0.50 | ⚡⚡⚡ | ~$0.0002 | Cheapest paid, 2M context (overkill here) |
| **DeepSeek V4 Flash** | $0.14 / $0.28 | ⚡⚡ | ~$0.0001 | Cheapest overall, good quality |
| **Gemini 3 Flash** | $0.50 / $3.00 | ⚡⚡ | ~$0.001 | Solid all-rounder |
| **Claude Sonnet 4.6** | $3 / $15 | ⚡ | ~$0.005 | Best music knowledge, 10x pricier |
| **GPT-5.4** | $3 / $15 | ⚡ | ~$0.005 | Excellent but overkill for this task |

At ~1K tokens per request, even 50 recommendations/day cost under 3 cents with Flash Lite. Use a premium model only if you want better curation of obscure genres.

## Troubleshooting

<details>
<summary>No audio after boot</summary>

```bash
# Check Bluetooth connection
ssh <user>@<host> "bluetoothctl info <BT_MAC> | grep Connected"

# Force reconnect
ssh <user>@<host> "bluetoothctl connect <BT_MAC> && sudo systemctl restart snapclient"
```

The watchdog should auto-reconnect within 5 seconds.
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
<summary>AirPlay: iPhone doesn't see "Jukebox"</summary>

Check mDNS is working and shairport-sync is running:

```bash
ssh <user>@<host> "avahi-browse -at | grep -i jukebox"
ssh <user>@<host> "sudo systemctl status shairport-sync"
```

The Pi and iPhone must be on the same network (mDNS doesn't cross subnets).
</details>

<details>
<summary>AirPlay: no audio or metadata</summary>

Check port 5000 is owned by shairport-sync (not Flask):

```bash
ssh <user>@<host> "sudo ss -tlnp | grep :5000"
```

Should show `shairport-sync`. If Flask took the port, it fights with AirPlay for
the RTSP listener. The Flask dashboard must run on port 8080.
</details>

<details>
<summary>Service logs</summary>

```bash
ssh <user>@<host> "journalctl -u snapclient --no-pager -n 20"
ssh <user>@<host> "journalctl -u bt-autoconnect --no-pager -n 20"
ssh <user>@<host> "journalctl -u jukebox-web --no-pager -n 20"
ssh <user>@<host> "journalctl -u shairport-sync --no-pager -n 20"
```
</details>

### Performance Notes

Buffer warnings in snapclient logs (`pShortBuffer`, `pBuffer`, `pMiniBuffer`) indicate Snapcast correcting timing drift — normal on WiFi. The `--latency 500` flag adds 500ms of extra PCM buffer in PulseAudio to absorb WiFi jitter before it causes audible glitches.

The CPU governor is set to `performance` (constant 1 GHz) to avoid clock-scaling delays that cause audio underruns. The `ondemand` governor is too slow to ramp up for real-time audio processing on the Pi Zero 2 W.

If you use the USB WiFi adapter, onboard WiFi is automatically disabled to prevent dual-homing (two interfaces in the same subnet), which causes routing instability and packet loss. The USB adapter's `autosuspend` is disabled via udev rule and kernel parameter to prevent the Pi's `dwc_otg` USB controller from dropping the device.

Snapclient uses `--hostID jukebox` to register with a fixed identifier on the Snapcast server. Without this, Snapcast identifies clients by MAC address, and switching between onboard WiFi and the USB adapter creates ghost clients on different streams.

If you still hear stutters, increase the Music Assistant Snapcast buffer (currently 2000ms) further, or reduce chunk size to 20ms for finer correction granularity.

ALSA output is not an option because PipeWire is required for Bluetooth A2DP routing. The `--player pulse` flag works because PipeWire provides PulseAudio compatibility.

## License

[MIT](LICENSE)
