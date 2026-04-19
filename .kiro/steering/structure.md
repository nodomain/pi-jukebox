# Project Structure

```
.
├── .env.example          # Template for environment variables
├── .env                  # Local config (gitignored): user, host, BT MAC, server IP, MA token
├── .gitignore
├── README.md             # Full project documentation, setup guide, troubleshooting
├── scripts/
│   ├── deploy.sh         # Deploy web dashboard to the Pi via SCP + SSH (run from dev machine)
│   ├── setup.sh          # Pi provisioning script (installs packages, creates systemd services, deploys app)
│   └── pair-bt.sh        # Bluetooth speaker pairing script
└── web/                  # Flask web dashboard (deployed to /opt/jukebox/ on the Pi)
    ├── app.py            # Flask application — all API routes, SSE endpoints, MA WebSocket relay
    ├── cava.conf         # cava config for FFT visualizer (48 bars, PipeWire input, ASCII output)
    └── templates/
        └── index.html    # Single-page dashboard — HTML, CSS, and JS all inline
```

## Key Conventions

- **Monolithic Flask app** — all routes live in `web/app.py` (no blueprints, no separate modules)
- **Single HTML file** — all frontend code (markup, styles, scripts) is in `web/templates/index.html`
- **Shell scripts in `scripts/`** — `setup.sh` and `pair-bt.sh` run on the Pi, `deploy.sh` runs on the dev machine
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
