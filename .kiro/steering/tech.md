# Tech Stack

## Backend

- **Python 3** with **Flask** — web dashboard (`web/app.py`)
- `python3-flask` (system package, not pip)
- `python3-websocket` (`websocket-client`) for Music Assistant WebSocket connection
- No virtual environment — uses system Python on the Pi

## Frontend

- **Vanilla HTML/CSS/JS** — single-page app in `web/templates/index.html`
- **Chart.js 4** via CDN (`chart.umd.min.js`) — live system metric charts
- No build step, no bundler, no framework
- Dark theme, mobile-first responsive layout (up to 1200px)

## System Services

- **Snapcast** client (`snapclient`) — audio streaming
- **PipeWire + WirePlumber** — Bluetooth A2DP audio backend
- **BlueZ** — Bluetooth stack
- **cava** — console audio visualizer, used for FFT data streamed via SSE
- **NetworkManager** — WiFi management

## APIs & Protocols

- **Snapcast JSON-RPC** (HTTP POST to port 1780) — playback control, client status
- **Music Assistant WebSocket** (port 8095) — real-time queue/player events via SSE relay
- **Music Assistant HTTP API** (port 8095) — queue items, track metadata, image proxy
- **Server-Sent Events (SSE)** — two endpoints: `/api/ma/events` (MA events) and `/api/fft/stream` (cava FFT)
- **D-Bus / bluetoothctl** — Bluetooth pairing, connect, disconnect
- **PipeWire CLI** (`wpctl`, `pw-dump`, `pw-cli`) — audio sink control, codec info

## Shell Scripts

- `scripts/setup.sh` — full Pi provisioning, idempotent (run as root, reads `.env`)
- `scripts/pair-bt.sh` — Bluetooth speaker pairing (run as root after setup + reboot)
- All use `bash` with `set -euo pipefail`

## Configuration

- `.env` file (copied from `.env.example`) — user, host, Snapcast server IP, BT MAC, MA token
- `.env` is gitignored

## Deployment

No CI/CD. Makefile wraps SCP + SSH:

```bash
make deploy    # deploy web dashboard
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

# Run Flask app locally (for development — won't have Pi hardware APIs)
cd web && python3 app.py
```

## No Test Suite

There are currently no automated tests, linters, or formatters configured in this project.
