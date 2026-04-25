# Tech Stack

## Backend

- **Python 3** with **Flask** — web dashboard (`web/app.py`)
- `python3-flask` (system package, not pip)
- `python3-websocket` (`websocket-client`) for Music Assistant WebSocket connection
- No virtual environment — uses system Python on the Pi
- Routes split into **Flask blueprints** in `web/routes/`

## Frontend

- **Vanilla HTML/CSS/JS** — single-page app in `web/templates/index.html`
- **ES modules** in `web/js/`, bundled to `web/static/app.js` via **esbuild**
- **Chart.js 4** via CDN (`chart.umd.min.js`) — live system metric charts
- Build step: `npm run build` (in `web/`) — required before deploy
- Dark theme, mobile-first responsive layout (up to 1200px)

## System Services

- **Snapcast** client (`snapclient`) — audio streaming (500ms latency buffer)
- **PipeWire + WirePlumber** — Bluetooth A2DP audio backend
- **BlueZ** — Bluetooth stack
- **shairport-sync** — AirPlay receiver
- **raspotify** (librespot) — Spotify Connect receiver
- **cava** — console audio visualizer, used for FFT data streamed via SSE
- **NetworkManager** — WiFi management
- **cpu-performance.service** — pins CPU governor to `performance` (1 GHz constant)

## WiFi & Audio Stability

- **USB WiFi adapter** (TP-Link AC600, RTL8812AU) on 5 GHz with out-of-tree `88XXau` driver
- **Onboard WiFi auto-disabled** when USB adapter is present (udev rule + `/usr/local/bin/wifi-switch`)
- **USB autosuspend disabled** — udev rule (`71-wifi-usb-power.conf`) + kernel param `usbcore.autosuspend=-1`
- **dwc_otg stabilized** — kernel param `dwc_otg.fiq_fsm_mask=0x7` for Pi Zero 2 W USB controller
- **WiFi power save disabled** — NetworkManager `wifi.powersave = 2`
- **Snapclient buffer: 500ms** (`--latency 500`) — absorbs WiFi jitter
- **Snapclient hostID: fixed** (`--hostID jukebox`) — prevents ghost clients when WiFi interface MAC changes

## APIs & Protocols

- **Snapcast JSON-RPC** (HTTP POST to port 1780) — playback control, client status
- **Music Assistant WebSocket** (port 8095) — real-time queue/player events via SSE relay
- **Music Assistant HTTP API** (port 8095) — queue items, track metadata, image proxy
- **LRCLIB API** (`lrclib.net`) — synced lyrics (free, no API key needed)
- **Last.fm API** (`ws.audioscrobbler.com`) — similar tracks/artists for recommendations
- **OpenRouter API** (`openrouter.ai`) — LLM curation of recommendations (Gemini Flash Lite default)
- **Server-Sent Events (SSE)** — two endpoints: `/api/ma/events` (MA events) and `/api/fft/stream` (cava FFT)
- **D-Bus / bluetoothctl** — Bluetooth pairing, connect, disconnect
- **PipeWire CLI** (`wpctl`, `pw-dump`, `pw-cli`) — audio sink control, codec info

## Shell Scripts

- `scripts/setup.sh` — full Pi provisioning, idempotent (run as root, reads `.env`)
- `scripts/pair-bt.sh` — Bluetooth speaker pairing (run as root after setup + reboot)
- `scripts/build-wifi-driver.sh` — cross-compile RTL8812AU driver via Docker (run on dev machine)
- All use `bash` with `set -euo pipefail`

## Configuration

- `.env` file (copied from `.env.example`) — user, host, Snapcast server IP, BT MAC, MA token
- `.env` is gitignored
- Kernel boot params in `/boot/firmware/cmdline.txt` — USB autosuspend, dwc_otg stability

## Deployment

No CI/CD. Makefile wraps SCP + SSH:

```bash
make build     # bundle JS modules with esbuild
make deploy    # build + deploy web dashboard
make setup     # full Pi provisioning
make pair      # Bluetooth pairing
make status    # check services + BT + Snapcast
make logs      # tail service logs
```

Or use the scripts directly: `./scripts/setup.sh`, `./scripts/pair-bt.sh`.

## Common Commands

```bash
# Deploy web changes to Pi (from dev machine)
make deploy

# Full Pi provisioning (from dev machine)
make setup

# Pair Bluetooth speaker (from dev machine, speaker in pairing mode)
make pair

# Check status
make status

# Tail logs
make logs

# Build USB WiFi driver (from dev machine, needs Docker)
./scripts/build-wifi-driver.sh

# Run Flask app locally (for development — won't have Pi hardware APIs)
cd web && python3 app.py
```

## No Test Suite

There are currently no automated tests, linters, or formatters configured in this project.
