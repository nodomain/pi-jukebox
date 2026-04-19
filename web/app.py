#!/usr/bin/env python3
"""Jukebox Pi Web Dashboard."""

import json
import re
import subprocess
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

SNAPCAST_SERVER = "192.168.10.250"


def run(cmd, timeout=5):
    """Run a shell command and return stdout."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, Exception):
        return ""


def run_pw(cmd):
    """Run a PipeWire command with correct env."""
    return run(f"XDG_RUNTIME_DIR=/run/user/1000 {cmd}")


def snapcast_rpc(method, params=None):
    """Call Snapcast JSON-RPC."""
    payload = {"id": 1, "jsonrpc": "2.0", "method": method}
    if params:
        payload["params"] = params
    raw = run(
        f"curl -s -m 3 -X POST -H 'Content-Type: application/json' "
        f"-d '{json.dumps(payload)}' http://{SNAPCAST_SERVER}:1780/jsonrpc"
    )
    if not raw:
        return None
    try:
        return json.loads(raw).get("result")
    except (json.JSONDecodeError, KeyError):
        return None


def decode_throttle(val):
    """Decode vcgencmd get_throttled value into flags."""
    try:
        v = int(val, 16) if isinstance(val, str) else int(val)
    except (ValueError, TypeError):
        return {}
    return {
        "under_voltage": bool(v & 0x1),
        "freq_capped": bool(v & 0x2),
        "throttled": bool(v & 0x4),
        "soft_temp_limit": bool(v & 0x8),
        "under_voltage_occurred": bool(v & 0x10000),
        "freq_capped_occurred": bool(v & 0x20000),
        "throttled_occurred": bool(v & 0x40000),
        "soft_temp_limit_occurred": bool(v & 0x80000),
    }


# --- Pages ---


@app.route("/")
def index():
    return render_template("index.html")


# --- System Stats API ---


@app.route("/api/stats")
def stats():
    # CPU temp
    temp = run("vcgencmd measure_temp").replace("temp=", "").replace("'C", "")

    # Uptime + load
    uptime_raw = run("cat /proc/uptime").split()[0]
    load = run("cat /proc/loadavg").split()[:3]

    # Memory
    meminfo = run("cat /proc/meminfo")
    mem = {}
    for line in meminfo.splitlines():
        parts = line.split()
        if parts[0] in ("MemTotal:", "MemAvailable:"):
            mem[parts[0].rstrip(":")] = int(parts[1])
    mem_used = mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)
    mem_total = mem.get("MemTotal", 0)

    # CPU frequency
    cpu_freq_raw = run("vcgencmd measure_clock arm")
    cpu_freq = 0
    m = re.search(r"=(\d+)", cpu_freq_raw)
    if m:
        cpu_freq = int(m.group(1)) / 1_000_000  # MHz

    # WiFi
    wifi = {}
    station = run("/usr/sbin/iw dev wlan0 station dump")
    for line in station.splitlines():
        line = line.strip()
        if line.startswith("signal:"):
            wifi["signal"] = line.split(":")[1].strip()
        elif line.startswith("tx bitrate:"):
            wifi["tx_bitrate"] = line.split(":")[1].strip()
        elif line.startswith("rx bitrate:"):
            wifi["rx_bitrate"] = line.split(":")[1].strip()
    link = run("/usr/sbin/iw dev wlan0 link")
    for line in link.splitlines():
        line = line.strip()
        if line.startswith("SSID:"):
            wifi["ssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("freq:"):
            wifi["freq"] = line.split(":")[1].strip()

    # WiFi traffic
    net = run("cat /proc/net/dev | grep wlan0").split()
    if len(net) > 9:
        wifi["rx_bytes"] = int(net[1])
        wifi["tx_bytes"] = int(net[9])
        wifi["rx_packets"] = int(net[2])
        wifi["tx_packets"] = int(net[10])

    # SD card writes
    diskstats = run("cat /proc/diskstats | grep 'mmcblk0 '")
    sd_writes = 0
    if diskstats:
        parts = diskstats.split()
        if len(parts) > 7:
            sd_writes = int(parts[7])

    # Throttle
    throttle_raw = run("vcgencmd get_throttled").replace("throttled=", "")
    throttle = decode_throttle(throttle_raw)
    throttle["raw"] = throttle_raw

    return jsonify(
        {
            "temp": float(temp) if temp else 0,
            "uptime": float(uptime_raw) if uptime_raw else 0,
            "load": load,
            "mem_used_kb": mem_used,
            "mem_total_kb": mem_total,
            "cpu_freq_mhz": cpu_freq,
            "wifi": wifi,
            "sd_writes": sd_writes,
            "throttle": throttle,
        }
    )


# --- Bluetooth API ---


@app.route("/api/bt/status")
def bt_status():
    info = run("bluetoothctl info 2>/dev/null")
    connected = "Connected: yes" in info
    name = ""
    mac = ""
    codec = ""
    for line in info.splitlines():
        line = line.strip()
        if line.startswith("Name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Device"):
            mac = line.split()[1] if len(line.split()) > 1 else ""

    # Get codec from PipeWire
    pw = run_pw("pw-dump 2>/dev/null")
    try:
        for obj in json.loads(pw):
            props = obj.get("info", {}).get("props", {})
            if "bluez_output" in props.get("node.name", ""):
                codec = props.get("api.bluez5.codec", "")
    except (json.JSONDecodeError, TypeError):
        pass

    return jsonify(
        {"connected": connected, "name": name, "mac": mac, "codec": codec}
    )


@app.route("/api/bt/scan", methods=["POST"])
def bt_scan():
    run("bluetoothctl --timeout 10 scan on", timeout=15)
    devices_raw = run("bluetoothctl devices")
    devices = []
    for line in devices_raw.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            devices.append({"mac": parts[1], "name": parts[2]})
    return jsonify({"devices": devices})


@app.route("/api/bt/pair", methods=["POST"])
def bt_pair():
    mac = request.json.get("mac", "")
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac):
        return jsonify({"error": "Invalid MAC"}), 400
    out = run(f"bluetoothctl pair {mac}", timeout=15)
    run(f"bluetoothctl trust {mac}")
    return jsonify({"result": out})


@app.route("/api/bt/connect", methods=["POST"])
def bt_connect():
    mac = request.json.get("mac", "")
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac):
        return jsonify({"error": "Invalid MAC"}), 400
    out = run(f"bluetoothctl connect {mac}", timeout=10)
    return jsonify({"result": out, "success": "successful" in out.lower()})


@app.route("/api/bt/disconnect", methods=["POST"])
def bt_disconnect():
    mac = request.json.get("mac", "")
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac):
        return jsonify({"error": "Invalid MAC"}), 400
    out = run(f"bluetoothctl disconnect {mac}")
    return jsonify({"result": out})


# --- Audio API ---


@app.route("/api/audio/status")
def audio_status():
    status = run_pw("wpctl status 2>/dev/null")
    sinks = []
    default_sink = ""
    in_sinks = False
    for line in status.splitlines():
        if "Sinks:" in line:
            in_sinks = True
            continue
        if in_sinks:
            if line.strip() == "" or "Sources:" in line or "Filters:" in line:
                break
            m = re.match(
                r"\s*[│├└─\s]*(\*?)\s*(\d+)\.\s+(.+?)(?:\s+\[vol:\s*([\d.]+)\])?$",
                line,
            )
            if m:
                is_default = m.group(1) == "*"
                sink = {
                    "id": int(m.group(2)),
                    "name": m.group(3).strip(),
                    "volume": float(m.group(4)) if m.group(4) else None,
                    "default": is_default,
                }
                sinks.append(sink)
                if is_default:
                    default_sink = sink["name"]

    return jsonify({"sinks": sinks, "default_sink": default_sink})


@app.route("/api/audio/volume", methods=["POST"])
def audio_volume():
    vol = request.json.get("volume")
    if vol is None:
        return jsonify({"error": "Missing volume"}), 400
    vol = max(0.0, min(1.5, float(vol)))
    run_pw(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {vol}")
    return jsonify({"volume": vol})


# --- Snapcast API ---


@app.route("/api/snapcast/status")
def snapcast_status():
    try:
        result = snapcast_rpc("Server.GetStatus")
        if not result:
            return jsonify({"error": "Snapcast unreachable"}), 500
        server = result["server"]

        clients = []
        for g in server["groups"]:
            stream_id = g["stream_id"]
            for c in g["clients"]:
                clients.append(
                    {
                        "name": c["config"]["name"] or c["host"]["name"],
                        "ip": c["host"]["ip"],
                        "connected": c["connected"],
                        "volume": c["config"]["volume"]["percent"],
                        "muted": c["config"]["volume"]["muted"],
                        "latency": c["config"].get("latency", 0),
                        "stream": stream_id,
                    }
                )

        streams = []
        now_playing = None
        for s in server["streams"]:
            meta = s.get("properties", {}).get("metadata", {})
            si = {"id": s["id"], "status": s["status"]}
            if meta:
                si["metadata"] = {
                    "artist": meta.get("artist", ""),
                    "title": meta.get("title", ""),
                    "album": meta.get("album", ""),
                    "artUrl": meta.get("artUrl", ""),
                }
            streams.append(si)
            if s["status"] == "playing" and meta:
                now_playing = si["metadata"]

        controls = {}
        for s in server["streams"]:
            props = s.get("properties", {})
            if s["status"] == "playing":
                controls = {
                    "canPlay": props.get("canPlay", False),
                    "canPause": props.get("canPause", False),
                    "canGoNext": props.get("canGoNext", False),
                    "canGoPrevious": props.get("canGoPrevious", False),
                    "canSeek": props.get("canSeek", False),
                    "streamId": s["id"],
                }
                break

        return jsonify(
            {
                "clients": clients,
                "streams": streams,
                "now_playing": now_playing,
                "controls": controls,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/snapcast/control", methods=["POST"])
def snapcast_control():
    """Control playback via Snapcast Stream.Control."""
    action = request.json.get("action", "")
    stream_id = request.json.get("streamId", "")
    if not action or not stream_id:
        return jsonify({"error": "Missing action or streamId"}), 400

    command_map = {
        "play": "play",
        "pause": "pause",
        "next": "next",
        "previous": "previous",
    }
    cmd = command_map.get(action)
    if not cmd:
        return jsonify({"error": "Unknown action"}), 400

    result = snapcast_rpc(
        "Stream.Control", {"id": stream_id, "command": cmd}
    )
    return jsonify({"result": result or "ok"})


# --- Service Control ---


@app.route("/api/service/<action>", methods=["POST"])
def service_control(action):
    if action == "restart-snapclient":
        run("sudo systemctl restart snapclient")
        return jsonify({"result": "ok"})
    elif action == "restart-bt":
        run("sudo systemctl restart bt-autoconnect")
        return jsonify({"result": "ok"})
    elif action == "reboot":
        run("sudo reboot &")
        return jsonify({"result": "rebooting"})
    return jsonify({"error": "unknown action"}), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
