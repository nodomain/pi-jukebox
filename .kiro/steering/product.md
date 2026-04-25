# Product: Jukebox Pi

Headless Raspberry Pi Zero 2 W that acts as a Snapcast client, streaming audio from Music Assistant (Home Assistant add-on) to a Bluetooth speaker over A2DP. Also supports AirPlay (shairport-sync) and Spotify Connect (raspotify/librespot) as alternative audio sources.

## Key Goals

- Battery/portable use — safe to pull power at any time
- Zero SD card writes during normal operation (tmpfs + volatile journal)
- Auto-reconnect to Bluetooth speaker on boot or power-cycle
- SBC-XQ codec for better Bluetooth audio quality
- Stable audio streaming — USB WiFi on 5 GHz, CPU pinned to max, 500ms Snapclient buffer

## Audio Sources

Three sources share the same Bluetooth output. When AirPlay or Spotify starts, Snapcast is paused automatically; when they end, Snapcast resumes.

1. **Music Assistant** → Snapcast Server → Snapcast Client (Pi)
2. **AirPlay** → shairport-sync (Pi)
3. **Spotify Connect** → raspotify/librespot (Pi)

All three → PipeWire/PulseAudio → Bluetooth A2DP (SBC-XQ) → Speaker

## WiFi & Audio Stability

- **USB WiFi adapter** (TP-Link AC600, RTL8812AU) on 5 GHz — onboard WiFi auto-disabled when USB is present
- **USB autosuspend disabled** — udev rule + kernel param (`usbcore.autosuspend=-1`) prevents USB disconnects
- **dwc_otg stabilized** — `dwc_otg.fiq_fsm_mask=0x7` kernel param for Pi Zero 2 W USB controller
- **CPU governor: performance** — constant 1 GHz, no clock-scaling delays for real-time audio
- **Snapclient buffer: 500ms** — absorbs WiFi jitter without audible glitches
- **Snapclient hostID: fixed** — `--hostID jukebox` prevents ghost clients when WiFi MAC changes
- **WiFi power save disabled** — NetworkManager config prevents latency spikes

## Web Dashboard

Flask app served on port 8080 providing:

- Now Playing with album art, playback controls, progress bar, lyrics
- AirPlay / Spotify Connect now-playing when those sources are active
- FFT audio visualizer via cava
- Queue browser with reorder/delete/shuffle/repeat
- Music search, recently played, playlists
- Three volume sliders (Music Assistant, Snapcast, PipeWire)
- System diagnostics: CPU temp/freq, memory, WiFi signal, SD writes, throttle flags
- Live Chart.js charts for system metrics and Snapcast buffer jitter
- Bluetooth device scanning, connect/disconnect
- Service management: restart snapclient, BT watchdog, reboot

## Target Hardware

Raspberry Pi Zero 2 W running Raspberry Pi OS Lite (64-bit, Debian Trixie).
Optional: TP-Link AC600 (Archer T2U Nano) USB WiFi adapter for 5 GHz.
