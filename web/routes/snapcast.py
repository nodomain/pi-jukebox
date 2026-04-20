"""Snapcast API blueprint for Jukebox Pi.

Endpoints:
    GET  /api/snapcast/status  — server status, clients, streams, now playing
    POST /api/snapcast/control — playback control (play/pause/next/prev/seek)
    GET  /api/snapcast/jitter  — buffer jitter from snapclient journal logs
"""

import json
import os
import re

from flask import Blueprint, jsonify, request  # pylint: disable=import-error

from helpers import run  # pylint: disable=import-error

snap_bp = Blueprint("snapcast", __name__)

SNAPCAST_SERVER = os.environ.get("SNAPCAST_SERVER", "192.168.10.250")


def snapcast_rpc(method, params=None):
    """Call Snapcast JSON-RPC.

    Args:
        method: JSON-RPC method name.
        params: Optional dict of parameters.

    Returns:
        The 'result' field from the response, or None on failure.
    """
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


@snap_bp.route("/api/snapcast/status")
def snapcast_status():
    """Return Snapcast server status: clients, streams, now playing."""
    data = snapcast_status_data()
    if "error" in data:
        return jsonify(data), 500
    return jsonify(data)


def snapcast_status_data():
    """Collect Snapcast status as a dict (no Flask response).

    Returns:
        Dict with clients, streams, now_playing, controls. Or dict with
        'error' key on failure.
    """
    try:
        result = snapcast_rpc("Server.GetStatus")
        if not result:
            return {"error": "Snapcast unreachable"}
        server = result["server"]

        clients = []
        for group in server["groups"]:
            stream_id = group["stream_id"]
            for client in group["clients"]:
                clients.append({
                    "name": client["config"]["name"] or client["host"]["name"],
                    "ip": client["host"]["ip"],
                    "connected": client["connected"],
                    "volume": client["config"]["volume"]["percent"],
                    "muted": client["config"]["volume"]["muted"],
                    "latency": client["config"].get("latency", 0),
                    "stream": stream_id,
                })

        streams = []
        now_playing = None
        for stream in server["streams"]:
            meta = stream.get("properties", {}).get("metadata", {})
            stream_info = {"id": stream["id"], "status": stream["status"]}
            if meta:
                stream_info["metadata"] = {
                    "artist": meta.get("artist", ""),
                    "title": meta.get("title", ""),
                    "album": meta.get("album", ""),
                    "artUrl": meta.get("artUrl", ""),
                }
            streams.append(stream_info)
            if stream["status"] == "playing" and meta:
                now_playing = stream_info["metadata"]
                now_playing["duration"] = meta.get("duration", 0)
                pos = stream.get("properties", {}).get("position", 0)
                now_playing["position"] = pos

        controls = {}
        for stream in server["streams"]:
            props = stream.get("properties", {})
            if stream["status"] == "playing":
                controls = {
                    "canPlay": props.get("canPlay", False),
                    "canPause": props.get("canPause", False),
                    "canGoNext": props.get("canGoNext", False),
                    "canGoPrevious": props.get("canGoPrevious", False),
                    "canSeek": props.get("canSeek", False),
                    "streamId": stream["id"],
                }
                break

        return {
            "clients": clients,
            "streams": streams,
            "now_playing": now_playing,
            "controls": controls,
        }
    except (KeyError, TypeError) as exc:
        return {"error": str(exc)}


@snap_bp.route("/api/snapcast/control", methods=["POST"])
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


@snap_bp.route("/api/snapcast/jitter")
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
        match = re.search(
            r"(pMiniBuffer|pShortBuffer|pBuffer).+?:\s*(-?\d+)", msg
        )
        if match:
            points.append(
                {"ts": ts, "type": match.group(1), "us": int(match.group(2))}
            )
    return jsonify({"points": points})
