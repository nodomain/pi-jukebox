# Product: Jukebox Pi

Headless Raspberry Pi Zero 2 W that acts as a Snapcast client, streaming audio from Music Assistant (Home Assistant add-on) to a Bluetooth speaker over A2DP.

## Key Goals

- Battery/portable use — safe to pull power at any time
- Zero SD card writes during normal operation (tmpfs + volatile journal)
- Auto-reconnect to Bluetooth speaker on boot or power-cycle
- SBC-XQ codec for better Bluetooth audio quality

## Audio Chain

Music Assistant → Snapcast Server → (network) → Snapcast Client (Pi) → PipeWire/PulseAudio → Bluetooth A2DP → Speaker

## Web Dashboard

Flask app served on port 8080 providing:

- Now Playing with album art, playback controls, progress bar, lyrics
- FFT audio visualizer via cava
- Queue browser with reorder/delete/shuffle/repeat
- Volume control (PipeWire sink)
- System diagnostics: CPU temp/freq, memory, WiFi signal, SD writes, throttle flags
- Live Chart.js charts for system metrics and Snapcast buffer jitter
- Bluetooth device scanning, connect/disconnect
- Service management: restart snapclient, BT watchdog, reboot

## Target Hardware

Raspberry Pi Zero 2 W running Raspberry Pi OS Lite (64-bit, Debian Trixie).
