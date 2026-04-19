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

from flask import Flask, Response, jsonify, render_template, request

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


def ma_ws_thread():
    """Background thread: maintain WebSocket connection to Music Assistant."""
    try:
        import websocket
    except ImportError:
        app.logger.error("websocket-client not installed, WS disabled")
        return

    url = f"ws://{SNAPCAST_SERVER}:8095/ws"
    msg_id = 0

    def next_id():
        nonlocal msg_id
        msg_id += 1
        return str(msg_id)

    def broadcast(event_type, data):
        """Send SSE event to all connected browsers."""
        msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        with sse_lock:
            dead = []
            for q in sse_clients:
                try:
                    q.put_nowait(msg)
                except Exception:
                    dead.append(q)
            for q in dead:
                sse_clients.remove(q)

    while True:
        try:
            ws = websocket.create_connection(url, timeout=10)
            # Server sends info message first
            ws.recv()
            # Auth
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

            # Request initial queue state
            ws.send(json.dumps({
                "message_id": next_id(),
                "command": "player_queues/all",
                "args": {},
            }))

            while True:
                raw = ws.recv()
                if not raw:
                    break
                msg = json.loads(raw)

                # Handle events
                event = msg.get("event")
                if event in (
                    "queue_updated", "queue_items_updated",
                    "queue_time_updated", "player_updated",
                ):
                    data = msg.get("data", {})
                    # Update cached queue state for the playing queue
                    if event == "queue_updated":
                        with ma_state["lock"]:
                            ma_state["queue"] = data
                    broadcast(event, data)

                # Handle command responses (e.g. initial player_queues/all)
                result = msg.get("result")
                if result and isinstance(result, list):
                    for q in result:
                        if q.get("state") == "playing":
                            with ma_state["lock"]:
                                ma_state["queue"] = q
                            broadcast("queue_updated", q)
                            break

        except Exception as e:
            app.logger.warning(f"MA WS error: {e}")
            ma_state["connected"] = False
        time.sleep(5)  # reconnect delay


# Start WS thread
if MA_TOKEN:
    t = threading.Thread(target=ma_ws_thread, daemon=True)
    t.start()


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
                now_playing["duration"] = meta.get("duration", 0)
                now_playing["position"] = s.get("properties", {}).get("position", 0)

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
        data = json.loads(raw)
        # HTTP API returns result directly (no wrapper)
        return data
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
            # Send initial state
            with ma_state["lock"]:
                if ma_state["queue"]:
                    yield f"event: queue_updated\ndata: {json.dumps(ma_state['queue'])}\n\n"
            yield f"event: connected\ndata: {json.dumps({'ws': ma_state['connected']})}\n\n"
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

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/ma/queue")
def ma_queue():
    """Get active player queue from Music Assistant for track position."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500

    # Try cached WS state first, fall back to HTTP
    q = None
    with ma_state["lock"]:
        if ma_state["queue"] and ma_state["queue"].get("state") == "playing":
            q = ma_state["queue"]

    if not q:
        raw = run(
            f"curl -s -m 3 'http://{SNAPCAST_SERVER}:8095/api' "
            f"-H 'Content-Type: application/json' "
            f"-H 'Authorization: Bearer {MA_TOKEN}' "
            f"""-d '{{"message_id":"1","command":"player_queues/all"}}'""",
            timeout=5,
        )
        if not raw:
            return jsonify({"error": "MA unreachable"}), 500
        try:
            queues = json.loads(raw)
            if isinstance(queues, dict):
                queues = queues.get("result", [])
            for candidate in queues:
                if candidate.get("state") == "playing":
                    q = candidate
                    break
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if not q:
        return jsonify({"elapsed_time": 0, "duration": 0, "name": ""})

    try:
        ci = q.get("current_item") or {}
        ni = q.get("next_item") or {}
        sd = ci.get("streamdetails") or {}
        af = sd.get("audio_format") or {}
        mi = ci.get("media_item") or {}
        meta = mi.get("metadata") or {}

        # Audio quality badge
        codec = af.get("content_type", "")
        codec_type = af.get("codec_type", "")
        sr = af.get("sample_rate", 0)
        bits = af.get("bit_depth", 0)
        lossy_codecs = {"ogg", "aac", "mp3", "opus", "vorbis", "mp4"}
        lossy = codec in lossy_codecs or codec_type in lossy_codecs
        if lossy:
            quality = "LQ"
        elif sr > 48000 or bits > 16:
            quality = "HR"
        else:
            quality = "HQ"

        # Album art URL
        images = meta.get("images") or []
        image_url = ""
        for img in images:
            if img.get("type") == "thumb" and img.get("path"):
                image_url = img["path"]
                break
        if not image_url and images:
            image_url = images[0].get("path", "")

        # Fetch lyrics via track API
        lyrics = ""
        track_id = mi.get("item_id")
        track_uri = mi.get("uri", "")
        if track_id and track_uri:
            provider = "library"
            if "://" in track_uri:
                provider = track_uri.split("://")[0]
            ly_raw = run(
                f"curl -s -m 2 'http://{SNAPCAST_SERVER}:8095/api' "
                f"-H 'Content-Type: application/json' "
                f"-H 'Authorization: Bearer {MA_TOKEN}' "
                f"""-d '{{"message_id":"2","command":"music/tracks/get","args":{{"item_id":"{track_id}","provider_instance_id_or_domain":"{provider}"}}}}'""",
                timeout=3,
            )
            try:
                ly_data = json.loads(ly_raw) if ly_raw else {}
                ly_meta = ly_data.get("metadata") or {}
                lyrics = (
                    ly_meta.get("lrc_lyrics")
                    or ly_meta.get("lyrics")
                    or ""
                )
            except (json.JSONDecodeError, TypeError):
                pass

        return jsonify(
            {
                "elapsed_time": q.get("elapsed_time", 0),
                "elapsed_time_last_updated": q.get(
                    "elapsed_time_last_updated", 0
                ),
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
            }
        )
    except Exception as e:
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
    # Return simplified items
    items = []
    for item in (data if isinstance(data, list) else []):
        mi = item.get("media_item") or {}
        artists = mi.get("artists") or []
        artist_name = artists[0].get("name", "") if artists else ""
        # Extract from combined name "Artist - Title"
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
    # Proxy through MA's imageproxy
    proxy_url = (
        f"http://{SNAPCAST_SERVER}:8095/imageproxy"
        f"?path={urllib.request.quote(url, safe='')}&size=200&fmt=jpeg"
    )
    try:
        req = urllib.request.Request(proxy_url)
        req.add_header("Authorization", f"Bearer {MA_TOKEN}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            return Response(data, mimetype="image/jpeg",
                            headers={"Cache-Control": "public, max-age=3600"})
    except Exception:
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
        # Extract buffer type and value in µs
        m = re.search(r"(pMiniBuffer|pShortBuffer|pBuffer).+?:\s*(-?\d+)", msg)
        if m:
            points.append(
                {"ts": ts, "type": m.group(1), "us": int(m.group(2))}
            )
    return jsonify({"points": points})


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
