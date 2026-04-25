# Project Structure

```
.
├── .env.example              # Template for environment variables
├── .env                      # Local config (gitignored): user, host, BT MAC, server IP, MA token
├── .gitignore
├── Makefile                  # Dev machine targets (deploy, setup, logs, status, ...)
├── README.md                 # Full project documentation, setup guide, troubleshooting
├── scripts/
│   ├── setup.sh              # Pi provisioning — idempotent (run on Pi as root)
│   ├── pair-bt.sh            # Bluetooth speaker pairing (run on Pi as root)
│   └── build-wifi-driver.sh  # Cross-compile RTL8812AU driver (run on dev machine, needs Docker)
└── web/                      # Flask dashboard (deployed to /opt/jukebox/ on the Pi)
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
    │   ├── airplay.py        # shairport-sync metadata reader
    │   └── recommend.py      # AI recommendations (Last.fm + LLM), auto-recommend
    ├── js/                   # ES modules, bundled to static/app.js via esbuild
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
    ├── static/               # Bundled app.js + CSS + icons + service worker
    └── templates/
        └── index.html        # Single-page app (HTML only, JS is bundled)
```

## Key Conventions

- **Flask blueprints** — routes split by concern in `web/routes/`, registered in `web/app.py`
- **JS modules** — source in `web/js/`, bundled to `web/static/app.js` via esbuild (`npm run build`)
- **Single HTML template** — `web/templates/index.html` contains markup only, JS is bundled separately
- **Shell scripts in `scripts/`** — `setup.sh` and `pair-bt.sh` run on the Pi, `build-wifi-driver.sh` runs on the dev machine
- **No `src/` or `lib/` directories** — flat structure, everything is top-level, `scripts/`, or `web/`
- **On-Pi paths differ** — the app is deployed to `/opt/jukebox/` on the Pi; `web/` is the dev-side source

## Environment Variables (from `.env`)

| Variable | Purpose |
|---|---|
| `JUKEBOX_USER` | Linux username on the Pi |
| `JUKEBOX_HOST` | Pi hostname (e.g. `jukebox.local`) |
| `SNAPCAST_SERVER` | IP of the Snapcast / Home Assistant server |
| `BT_MAC` | Bluetooth MAC address of the speaker |
| `BT_DEVICE_NAME` | Friendly name of the Bluetooth speaker |
| `MA_TOKEN` | Music Assistant long-lived access token |
| `LASTFM_API_KEY` | Last.fm API key (free, for recommendations) |
| `OPENROUTER_API_KEY` | OpenRouter API key (for LLM-curated recommendations) |
| `OPENROUTER_MODEL` | OpenRouter model ID (default: `google/gemini-3.1-flash-lite-preview`) |
