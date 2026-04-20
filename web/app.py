#!/usr/bin/env python3
"""Jukebox Pi Web Dashboard."""

import json
import os
import queue
import re
import subprocess
import threading
import time
import urllib.request

from flask import Flask, Response, jsonify, render_template, request  # pylint: disable=import-error

app = Flask(__name__)

SNAPCAST_SERVER = os.environ.get("SNAPCAST_SERVER", "192.168.10.250")
MA_TOKEN = os.environ.get("MA_TOKEN", "")

# --- WebSocket to Music Assistant ---
# Shared state updated by WS thread, read by SSE/API
ma_state = {
    "queue": {},  # current playing queue object
    "lock": threading.Lock(),
    "connected": False,
}
# SSE subscribers: list of queue.Queue objects
sse_clients = []
sse_lock = threading.Lock()


def _ws_broadcast(event_type, data):
    """Send SSE event to all connected browsers."""
    msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with sse_lock:
        dead = []
        for q in sse_clients:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(q)
        for q in dead:
            sse_clients.remove(q)


def _ws_handle_message(msg):
    """Process a single WS message, update state and broadcast."""
    event = msg.get("event")
    if event in (
        "queue_updated", "queue_items_updated",
        "queue_time_updated", "player_updated",
    ):
        data = msg.get("data", {})
        if event == "queue_updated":
            with ma_state["lock"]:
                ma_state["queue"] = data
        _ws_broadcast(event, data)

    result = msg.get("result")
    if result and isinstance(result, list):
        for q in result:
            if q.get("state") == "playing":
                with ma_state["lock"]:
                    ma_state["queue"] = q
                _ws_broadcast("queue_updated", q)
                break


def ma_ws_thread():
    """Background thread: maintain WebSocket connection to Music Assistant."""
    try:
        import websocket  # pylint: disable=import-outside-toplevel,import-error
    except ImportError:
        app.logger.error("websocket-client not installed, WS disabled")
        return

    url = f"ws://{SNAPCAST_SERVER}:8095/ws"
    msg_id = 0

    def next_id():
        nonlocal msg_id
        msg_id += 1
        return str(msg_id)

    while True:
        try:
            ws = websocket.create_connection(url, timeout=10)
            ws.recv()  # server info message
            ws.send(json.dumps({
                "message_id": next_id(),
                "command": "auth",
                "args": {"token": MA_TOKEN},
            }))
            auth_resp = json.loads(ws.recv())
            if not auth_resp.get("result", {}).get("authenticated"):
                app.logger.error("MA WS auth failed")
                ws.close()
                time.sleep(10)
                continue

            ma_state["connected"] = True
            app.logger.info("MA WebSocket connected")
            ws.send(json.dumps({
                "message_id": next_id(),
                "command": "player_queues/all",
                "args": {},
            }))

            while True:
                raw = ws.recv()
                if not raw:
                    break
                _ws_handle_message(json.loads(raw))

        except (OSError, ValueError) as e:
            app.logger.warning("MA WS error: %s", e)
            ma_state["connected"] = False
        time.sleep(5)


# Start WS thread
if MA_TOKEN:
    _ws_thread = threading.Thread(target=ma_ws_thread, daemon=True)
    _ws_thread.start()


def run(cmd, timeout=5):
    """Run a shell command and return stdout."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
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
        f"-d '{json.dumps(payload)}' "
        f"http://{SNAPCAST_SERVER}:1780/jsonrpc"
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
    """Serve the main dashboard page."""
    return render_template("index.html")


# --- System Stats API ---


def _parse_wifi():
    """Parse WiFi stats from iw and /proc/net/dev."""
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

    net = run("cat /proc/net/dev | grep wlan0").split()
    if len(net) > 9:
        wifi["rx_bytes"] = int(net[1])
        wifi["tx_bytes"] = int(net[9])
        wifi["rx_packets"] = int(net[2])
        wifi["tx_packets"] = int(net[10])
    return wifi


@app.route("/api/stats")
def stats():
    """Return system stats: temp, CPU, memory, WiFi, SD writes, throttle."""
    temp = run("vcgencmd measure_temp").replace("temp=", "").replace("'C", "")
    uptime_raw = run("cat /proc/uptime").split()[0]
    load = run("cat /proc/loadavg").split()[:3]

    meminfo = run("cat /proc/meminfo")
    mem = {}
    for line in meminfo.splitlines():
        parts = line.split()
        if parts[0] in ("MemTotal:", "MemAvailable:"):
            mem[parts[0].rstrip(":")] = int(parts[1])
    mem_used = mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)
    mem_total = mem.get("MemTotal", 0)

    cpu_freq_raw = run("vcgencmd measure_clock arm")
    cpu_freq = 0
    m = re.search(r"=(\d+)", cpu_freq_raw)
    if m:
        cpu_freq = int(m.group(1)) / 1_000_000

    wifi = _parse_wifi()

    diskstats = run("cat /proc/diskstats | grep 'mmcblk0 '")
    sd_writes = 0
    if diskstats:
        parts = diskstats.split()
        if len(parts) > 7:
            sd_writes = int(parts[7])

    throttle_raw = run("vcgencmd get_throttled").replace("throttled=", "")
    throttle = decode_throttle(throttle_raw)
    throttle["raw"] = throttle_raw

    return jsonify({
        "temp": float(temp) if temp else 0,
        "uptime": float(uptime_raw) if uptime_raw else 0,
        "load": load,
        "mem_used_kb": mem_used,
        "mem_total_kb": mem_total,
        "cpu_freq_mhz": cpu_freq,
        "wifi": wifi,
        "sd_writes": sd_writes,
        "throttle": throttle,
    })


# --- Bluetooth API ---


def _find_bt_transport():
    """Find the active BlueZ MediaTransport1 D-Bus path."""
    raw = run(
        "busctl tree org.bluez 2>/dev/null | grep '/fd'"
    )
    for line in raw.splitlines():
        path = line.strip().lstrip("├─└─│ ")
        if "/fd" in path:
            return path
    return ""


@app.route("/api/bt/status")
def bt_status():
    """Return Bluetooth connection status, codec, and AVRCP volume."""
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

    pw = run_pw("pw-dump 2>/dev/null")
    try:
        for obj in json.loads(pw):
            props = obj.get("info", {}).get("props", {})
            if "bluez_output" in props.get("node.name", ""):
                codec = props.get("api.bluez5.codec", "")
    except (json.JSONDecodeError, TypeError):
        pass

    # AVRCP hardware volume (0-127)
    hw_volume = -1
    transport = _find_bt_transport()
    if transport and connected:
        vol_raw = run(
            f"busctl get-property org.bluez {transport} "
            f"org.bluez.MediaTransport1 Volume 2>/dev/null"
        )
        if vol_raw.startswith("q "):
            try:
                hw_volume = int(vol_raw.split()[1])
            except (ValueError, IndexError):
                pass

    return jsonify({
        "connected": connected, "name": name, "mac": mac,
        "codec": codec, "hw_volume": hw_volume,
    })


@app.route("/api/bt/volume", methods=["POST"])
def bt_volume():
    """Set AVRCP hardware volume on the Bluetooth speaker (0-127)."""
    vol = request.json.get("volume")
    if vol is None:
        return jsonify({"error": "Missing volume"}), 400
    vol = max(0, min(127, int(vol)))
    transport = _find_bt_transport()
    if not transport:
        return jsonify({"error": "No active BT transport"}), 404
    run(
        f"busctl set-property org.bluez {transport} "
        f"org.bluez.MediaTransport1 Volume q {vol}"
    )
    return jsonify({"volume": vol})


@app.route("/api/bt/scan", methods=["POST"])
def bt_scan():
    """Scan for nearby Bluetooth devices."""
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
    """Pair with a Bluetooth device by MAC address."""
    mac = request.json.get("mac", "")
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac):
        return jsonify({"error": "Invalid MAC"}), 400
    out = run(f"bluetoothctl pair {mac}", timeout=15)
    run(f"bluetoothctl trust {mac}")
    return jsonify({"result": out})


@app.route("/api/bt/connect", methods=["POST"])
def bt_connect():
    """Connect to a paired Bluetooth device."""
    mac = request.json.get("mac", "")
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac):
        return jsonify({"error": "Invalid MAC"}), 400
    out = run(f"bluetoothctl connect {mac}", timeout=10)
    return jsonify({"result": out, "success": "successful" in out.lower()})


@app.route("/api/bt/disconnect", methods=["POST"])
def bt_disconnect():
    """Disconnect a Bluetooth device."""
    mac = request.json.get("mac", "")
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac):
        return jsonify({"error": "Invalid MAC"}), 400
    out = run(f"bluetoothctl disconnect {mac}")
    return jsonify({"result": out})


# --- Audio API ---


@app.route("/api/audio/status")
def audio_status():
    """Return PipeWire audio sinks and default sink."""
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
                r"\s*[│├└─\s]*(\*?)\s*(\d+)\.\s+(.+?)"
                r"(?:\s+\[vol:\s*([\d.]+)\])?$",
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
    """Set PipeWire default sink volume."""
    vol = request.json.get("volume")
    if vol is None:
        return jsonify({"error": "Missing volume"}), 400
    vol = max(0.0, min(1.5, float(vol)))
    run_pw(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {vol}")
    return jsonify({"volume": vol})


# --- Snapcast API ---


@app.route("/api/snapcast/status")
def snapcast_status():
    """Return Snapcast server status: clients, streams, now playing."""
    try:
        result = snapcast_rpc("Server.GetStatus")
        if not result:
            return jsonify({"error": "Snapcast unreachable"}), 500
        server = result["server"]

        clients = []
        for g in server["groups"]:
            stream_id = g["stream_id"]
            for c in g["clients"]:
                clients.append({
                    "name": c["config"]["name"] or c["host"]["name"],
                    "ip": c["host"]["ip"],
                    "connected": c["connected"],
                    "volume": c["config"]["volume"]["percent"],
                    "muted": c["config"]["volume"]["muted"],
                    "latency": c["config"].get("latency", 0),
                    "stream": stream_id,
                })

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
                now_playing["duration"] = meta.get("duration", 0)
                pos = s.get("properties", {}).get("position", 0)
                now_playing["position"] = pos

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

        return jsonify({
            "clients": clients,
            "streams": streams,
            "now_playing": now_playing,
            "controls": controls,
        })
    except (KeyError, TypeError) as e:
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
        "seek": "seek",
    }
    cmd = command_map.get(action)
    if not cmd:
        return jsonify({"error": "Unknown action"}), 400

    params = {"id": stream_id, "command": cmd}
    if cmd == "seek" and "position" in (request.json or {}):
        params["position"] = float(request.json["position"])

    result = snapcast_rpc("Stream.Control", params)
    return jsonify({"result": result or "ok"})


# --- Music Assistant API ---


def ma_rpc(command, args=None):
    """Call MA HTTP API."""
    payload = {"message_id": "rpc", "command": command}
    if args:
        payload["args"] = args
    raw = run(
        f"curl -s -m 5 'http://{SNAPCAST_SERVER}:8095/api' "
        f"-H 'Content-Type: application/json' "
        f"-H 'Authorization: Bearer {MA_TOKEN}' "
        f"-d '{json.dumps(payload)}'",
        timeout=7,
    )
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


@app.route("/api/ma/events")
def ma_events():
    """SSE endpoint: stream MA WebSocket events to browser."""
    def stream():
        q = queue.Queue(maxsize=50)
        with sse_lock:
            sse_clients.append(q)
        try:
            with ma_state["lock"]:
                if ma_state["queue"]:
                    yield (
                        f"event: queue_updated\n"
                        f"data: {json.dumps(ma_state['queue'])}\n\n"
                    )
            yield (
                f"event: connected\n"
                f"data: {json.dumps({'ws': ma_state['connected']})}\n\n"
            )
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with sse_lock:
                if q in sse_clients:
                    sse_clients.remove(q)

    return Response(
        stream(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _fetch_active_queue():
    """Fetch the active playing queue from MA, trying WS cache first.

    Returns the queue dict, empty dict if no active queue, or None if
    MA is unreachable.
    """
    with ma_state["lock"]:
        if ma_state["queue"] and ma_state["queue"].get("state") == "playing":
            return ma_state["queue"]

    raw = run(
        f"curl -s -m 3 'http://{SNAPCAST_SERVER}:8095/api' "
        f"-H 'Content-Type: application/json' "
        f"-H 'Authorization: Bearer {MA_TOKEN}' "
        f"""-d '{{"message_id":"1","command":"player_queues/all"}}'""",
        timeout=5,
    )
    if not raw:
        return None
    try:
        queues = json.loads(raw)
        if isinstance(queues, dict):
            queues = queues.get("result", [])
        for candidate in queues:
            if candidate.get("state") == "playing":
                return candidate
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def _parse_queue_quality(audio_format):
    """Determine audio quality badge from stream audio format."""
    codec = audio_format.get("content_type", "")
    codec_type = audio_format.get("codec_type", "")
    sr = audio_format.get("sample_rate", 0)
    bits = audio_format.get("bit_depth", 0)
    lossy_codecs = {"ogg", "aac", "mp3", "opus", "vorbis", "mp4"}
    lossy = codec in lossy_codecs or codec_type in lossy_codecs
    if lossy:
        quality = "LQ"
    elif sr > 48000 or bits > 16:
        quality = "HR"
    else:
        quality = "HQ"
    return quality, codec, codec_type, sr, bits


def _fetch_lyrics(track_id, track_uri):
    """Fetch lyrics for a track from MA."""
    provider = "library"
    if "://" in track_uri:
        provider = track_uri.split("://")[0]
    ly_raw = run(
        f"curl -s -m 2 'http://{SNAPCAST_SERVER}:8095/api' "
        f"-H 'Content-Type: application/json' "
        f"-H 'Authorization: Bearer {MA_TOKEN}' "
        f"-d '{{\"message_id\":\"2\","
        f"\"command\":\"music/tracks/get\","
        f"\"args\":{{\"item_id\":\"{track_id}\","
        f"\"provider_instance_id_or_domain\":\"{provider}\"}}}}'",
        timeout=3,
    )
    try:
        ly_data = json.loads(ly_raw) if ly_raw else {}
        ly_meta = ly_data.get("metadata") or {}
        return ly_meta.get("lrc_lyrics") or ly_meta.get("lyrics") or ""
    except (json.JSONDecodeError, TypeError):
        return ""


@app.route("/api/ma/volume")
def ma_volume():
    """Get MA player volume for the Jukebox queue."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500
    data = ma_rpc("players/all")
    if not data:
        return jsonify({"error": "MA unreachable"}), 500
    # Find the player that matches our active queue
    for p in (data if isinstance(data, list) else []):
        if "jukebox" in p.get("display_name", "").lower():
            return jsonify({
                "volume": p.get("volume_level", 0),
                "muted": p.get("volume_muted", False),
                "player_id": p.get("player_id", ""),
                "name": p.get("display_name", ""),
            })
    return jsonify({"error": "Player not found"}), 404


@app.route("/api/ma/volume", methods=["POST"])
def ma_volume_set():
    """Set MA player volume."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500
    player_id = request.json.get("player_id", "")
    volume = request.json.get("volume")
    if not player_id or volume is None:
        return jsonify({"error": "Missing player_id or volume"}), 400
    volume = max(0, min(100, int(volume)))
    ma_rpc("players/cmd/volume_set", {
        "player_id": player_id, "volume_level": volume,
    })
    return jsonify({"volume": volume})


@app.route("/api/ma/queue")
def ma_queue():
    """Get active player queue from Music Assistant for track position."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500

    q = _fetch_active_queue()
    if q is None:
        return jsonify({"error": "MA unreachable"}), 500
    if not q:
        return jsonify({"elapsed_time": 0, "duration": 0, "name": ""})

    try:
        ci = q.get("current_item") or {}
        ni = q.get("next_item") or {}
        sd = ci.get("streamdetails") or {}
        af = sd.get("audio_format") or {}
        mi = ci.get("media_item") or {}
        meta = mi.get("metadata") or {}

        quality, codec, codec_type, sr, bits = _parse_queue_quality(af)

        images = meta.get("images") or []
        image_url = ""
        for img in images:
            if img.get("type") == "thumb" and img.get("path"):
                image_url = img["path"]
                break
        if not image_url and images:
            image_url = images[0].get("path", "")

        lyrics = ""
        track_id = mi.get("item_id")
        track_uri = mi.get("uri", "")
        if track_id and track_uri:
            lyrics = _fetch_lyrics(track_id, track_uri)

        return jsonify({
            "elapsed_time": q.get("elapsed_time", 0),
            "elapsed_time_last_updated": q.get("elapsed_time_last_updated", 0),
            "duration": ci.get("duration", 0),
            "name": ci.get("name", ""),
            "server_time": time.time(),
            "next_track": ni.get("name", ""),
            "next_duration": ni.get("duration", 0),
            "quality": quality,
            "codec": codec_type or codec,
            "sample_rate": sr,
            "bit_depth": bits,
            "queue_id": q.get("queue_id", ""),
            "queue_index": q.get("current_index", 0),
            "queue_total": q.get("items", 0),
            "shuffle": q.get("shuffle_enabled", False),
            "repeat": q.get("repeat_mode", "off"),
            "target_loudness": sd.get("target_loudness"),
            "popularity": meta.get("popularity"),
            "lyrics": lyrics,
            "image_url": image_url,
        })
    except (KeyError, TypeError) as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ma/queue/items")
def ma_queue_items():
    """Get queue items list."""
    queue_id = request.args.get("queue_id", "")
    limit = int(request.args.get("limit", "50"))
    offset = int(request.args.get("offset", "0"))
    if not queue_id:
        return jsonify({"error": "Missing queue_id"}), 400
    data = ma_rpc("player_queues/items", {
        "queue_id": queue_id, "limit": limit, "offset": offset,
    })
    if data is None:
        return jsonify({"error": "MA unreachable"}), 500
    items = []
    for item in (data if isinstance(data, list) else []):
        mi = item.get("media_item") or {}
        artists = mi.get("artists") or []
        artist_name = artists[0].get("name", "") if artists else ""
        name = item.get("name", "")
        items.append({
            "queue_item_id": item.get("queue_item_id", ""),
            "name": name,
            "duration": item.get("duration", 0),
            "sort_index": item.get("sort_index", 0),
            "artist": artist_name,
        })
    return jsonify({"items": items})


@app.route("/api/ma/queue/action", methods=["POST"])
def ma_queue_action():
    """Perform queue action: delete, move, play_index, clear."""
    body = request.json or {}
    action = body.get("action", "")
    queue_id = body.get("queue_id", "")
    if not queue_id:
        return jsonify({"error": "Missing queue_id"}), 400

    cmd_map = {
        "delete": ("player_queues/delete_item", {
            "queue_id": queue_id,
            "queue_item_id": body.get("queue_item_id", ""),
        }),
        "move": ("player_queues/move_item", {
            "queue_id": queue_id,
            "queue_item_id": body.get("queue_item_id", ""),
            "pos_shift": body.get("pos_shift", 0),
        }),
        "play_index": ("player_queues/play_index", {
            "queue_id": queue_id,
            "index": body.get("queue_item_id", ""),
        }),
        "clear": ("player_queues/clear", {"queue_id": queue_id}),
        "shuffle": ("player_queues/shuffle", {
            "queue_id": queue_id,
            "shuffle_enabled": body.get("enabled", False),
        }),
        "repeat": ("player_queues/repeat", {
            "queue_id": queue_id,
            "repeat_mode": body.get("mode", "off"),
        }),
    }
    if action not in cmd_map:
        return jsonify({"error": "Unknown action"}), 400

    command, args = cmd_map[action]
    result = ma_rpc(command, args)
    return jsonify({"result": result or "ok"})


@app.route("/api/ma/imageproxy")
def ma_imageproxy():
    """Proxy album art images from MA to avoid CORS issues."""
    url = request.args.get("url", "")
    if not url:
        return "", 400
    proxy_url = (
        f"http://{SNAPCAST_SERVER}:8095/imageproxy"
        f"?path={urllib.request.quote(url, safe='')}"
        f"&size=200&fmt=jpeg"
    )
    try:
        req = urllib.request.Request(proxy_url)
        req.add_header("Authorization", f"Bearer {MA_TOKEN}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            return Response(
                data, mimetype="image/jpeg",
                headers={"Cache-Control": "public, max-age=3600"},
            )
    except (OSError, ValueError):
        return "", 502


# --- Snapcast Buffer/Jitter API ---


@app.route("/api/snapcast/jitter")
def snapcast_jitter():
    """Parse recent snapclient journal logs for buffer jitter values."""
    raw = run(
        "journalctl -u snapclient --no-pager --since '2 minutes ago' "
        "-o short-unix 2>/dev/null | grep -E 'p(Short|Mini)?Buffer'",
        timeout=3,
    )
    points = []
    for line in raw.splitlines():
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        try:
            ts = float(parts[0])
        except ValueError:
            continue
        msg = parts[1]
        m = re.search(
            r"(pMiniBuffer|pShortBuffer|pBuffer).+?:\s*(-?\d+)", msg
        )
        if m:
            points.append(
                {"ts": ts, "type": m.group(1), "us": int(m.group(2))}
            )
    return jsonify({"points": points})


# --- Service Control ---


@app.route("/api/service/<action>", methods=["POST"])
def service_control(action):
    """Restart services or reboot the Pi."""
    if action == "restart-snapclient":
        run("sudo systemctl restart snapclient")
        return jsonify({"result": "ok"})
    if action == "restart-bt":
        run("sudo systemctl restart bt-autoconnect")
        return jsonify({"result": "ok"})
    if action == "reboot":
        run("sudo reboot &")
        return jsonify({"result": "rebooting"})
    return jsonify({"error": "unknown action"}), 400


# --- FFT Visualizer via cava (on-demand) ---

CAVA_CONF = os.path.join(os.path.dirname(__file__), "cava.conf")

# Shared cava process — starts when first browser connects, stops when last disconnects
_cava_lock = threading.Lock()
_cava_proc = None  # pylint: disable=invalid-name
_cava_clients = []  # list of queue.Queue


def _cava_reader():
    """Background thread: read cava stdout and broadcast to all SSE clients."""
    try:
        for line in _cava_proc.stdout:
            line = line.strip()
            if not line:
                continue
            msg = f"data: {line}\n\n"
            with _cava_lock:
                dead = []
                for q in _cava_clients:
                    try:
                        q.put_nowait(msg)
                    except queue.Full:
                        dead.append(q)
                for q in dead:
                    _cava_clients.remove(q)
    except (OSError, ValueError):
        pass


def _cava_start():
    """Start the shared cava process if not already running."""
    global _cava_proc  # pylint: disable=global-statement
    if _cava_proc is not None and _cava_proc.poll() is None:
        return
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = "/run/user/1000"
    try:
        _cava_proc = subprocess.Popen(
            ["cava", "-p", CAVA_CONF],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, bufsize=1, text=True,
        )
        t = threading.Thread(target=_cava_reader, daemon=True)
        t.start()
        app.logger.info("cava started (pid %d)", _cava_proc.pid)
    except OSError as e:
        app.logger.warning("cava failed to start: %s", e)


def _cava_stop():
    """Stop the shared cava process if no clients remain."""
    global _cava_proc  # pylint: disable=global-statement
    if _cava_proc is None:
        return
    if _cava_proc.poll() is None:
        _cava_proc.terminate()
        app.logger.info("cava stopped")
    _cava_proc = None


@app.route("/api/fft/stream")
def fft_stream():
    """SSE endpoint: stream cava FFT data to browser."""
    def stream():
        q = queue.Queue(maxsize=30)
        with _cava_lock:
            _cava_clients.append(q)
            _cava_start()
        try:
            while True:
                try:
                    msg = q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _cava_lock:
                if q in _cava_clients:
                    _cava_clients.remove(q)
                if not _cava_clients:
                    _cava_stop()

    return Response(
        stream(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
