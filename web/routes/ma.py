"""Music Assistant API blueprint for Jukebox Pi.

Contains the MA WebSocket relay thread, SSE broadcast, queue endpoints,
volume control, and image proxy.

Endpoints:
    GET  /api/ma/events       — SSE stream of MA WebSocket events
    GET  /api/ma/volume       — get MA player volume
    POST /api/ma/volume       — set MA player volume
    GET  /api/ma/queue        — active queue with track metadata
    GET  /api/ma/queue/items  — queue item list
    POST /api/ma/queue/action — queue actions (delete, move, play, clear, etc.)
    GET  /api/ma/imageproxy   — proxy album art from MA
"""

import json
import os
import queue
import threading
import time
import urllib.request

from flask import Blueprint, Response, jsonify, request  # pylint: disable=import-error

from helpers import run  # pylint: disable=import-error

ma_bp = Blueprint("ma", __name__)

SNAPCAST_SERVER = os.environ.get("SNAPCAST_SERVER", "192.168.10.250")
MA_TOKEN = os.environ.get("MA_TOKEN", "")

# --- Shared state updated by WS thread, read by SSE/API ---
ma_state = {
    "queue": {},
    "lock": threading.Lock(),
    "connected": False,
}

# SSE subscribers: list of queue.Queue objects
sse_clients = []
sse_lock = threading.Lock()


def _ws_broadcast(event_type, data):
    """Send SSE event to all connected browsers (both MA and unified)."""
    # Broadcast to legacy MA SSE clients
    msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with sse_lock:
        dead = []
        for client_q in sse_clients:
            try:
                client_q.put_nowait(msg)
            except queue.Full:
                dead.append(client_q)
        for client_q in dead:
            sse_clients.remove(client_q)
    # Also broadcast to unified SSE
    try:
        from routes.events import broadcast as unified_broadcast  # pylint: disable=import-outside-toplevel
        unified_broadcast(event_type, data)
    except Exception as exc:  # pylint: disable=broad-except
        import logging  # pylint: disable=import-outside-toplevel
        logging.getLogger(__name__).warning("unified broadcast failed: %s", exc)


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
        for queue_obj in result:
            if queue_obj.get("state") == "playing":
                with ma_state["lock"]:
                    ma_state["queue"] = queue_obj
                _ws_broadcast("queue_updated", queue_obj)
                break


def ma_ws_thread(app):
    """Background thread: maintain WebSocket connection to Music Assistant.

    Args:
        app: Flask application instance for logging.
    """
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
            ws = websocket.create_connection(url, timeout=60)
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

        except Exception as exc:  # pylint: disable=broad-except
            app.logger.warning("MA WS error: %s", exc)
            ma_state["connected"] = False
        time.sleep(5)


def start_ws_thread(app):
    """Start the MA WebSocket thread if MA_TOKEN is configured.

    Args:
        app: Flask application instance.
    """
    if MA_TOKEN:
        thread = threading.Thread(target=ma_ws_thread, args=(app,), daemon=True)
        thread.start()


def ma_rpc(command, args=None):
    """Call MA HTTP API.

    Args:
        command: MA API command string.
        args: Optional dict of arguments.

    Returns:
        Parsed JSON response, or None on failure.
    """
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


# --- SSE endpoint ---


@ma_bp.route("/api/ma/events")
def ma_events():
    """SSE endpoint: stream MA WebSocket events to browser."""
    def stream():
        client_q = queue.Queue(maxsize=50)
        with sse_lock:
            sse_clients.append(client_q)
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
                    msg = client_q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with sse_lock:
                if client_q in sse_clients:
                    sse_clients.remove(client_q)

    return Response(
        stream(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Queue helpers ---


def _fetch_active_queue():
    """Fetch the active playing queue from MA via HTTP.

    Always fetches fresh data to avoid stale timing info from WS cache.

    Returns:
        Queue dict if found, empty dict if no active queue, or None if
        MA is unreachable.
    """
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
        # Prefer playing queue, fall back to first available
        fallback = None
        for candidate in queues:
            if candidate.get("state") == "playing":
                return candidate
            if fallback is None:
                fallback = candidate
        return fallback or {}
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def _parse_queue_quality(audio_format):
    """Determine audio quality badge from stream audio format.

    Args:
        audio_format: Dict with content_type, codec_type, sample_rate, bit_depth.

    Returns:
        Tuple of (quality, codec, codec_type, sample_rate, bit_depth).
    """
    codec = audio_format.get("content_type", "")
    codec_type = audio_format.get("codec_type", "")
    sample_rate = audio_format.get("sample_rate", 0)
    bits = audio_format.get("bit_depth", 0)
    lossy_codecs = {"ogg", "aac", "mp3", "opus", "vorbis", "mp4"}
    lossy = codec in lossy_codecs or codec_type in lossy_codecs
    if lossy:
        quality = "LQ"
    elif sample_rate > 48000 or bits > 16:
        quality = "HR"
    else:
        quality = "HQ"
    return quality, codec, codec_type, sample_rate, bits


def _fetch_lyrics(track_id, track_uri):
    """Fetch lyrics for a track from MA.

    Args:
        track_id: MA track item ID.
        track_uri: MA track URI (used to determine provider).

    Returns:
        Lyrics string, or empty string if unavailable.
    """
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


# --- Volume endpoints ---


@ma_bp.route("/api/ma/volume")
def ma_volume():
    """Get MA player volume for the Jukebox queue."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500
    data = ma_rpc("players/all")
    if not data:
        return jsonify({"error": "MA unreachable"}), 500
    for player in (data if isinstance(data, list) else []):
        if "jukebox" in player.get("display_name", "").lower():
            return jsonify({
                "volume": player.get("volume_level", 0),
                "muted": player.get("volume_muted", False),
                "player_id": player.get("player_id", ""),
                "name": player.get("display_name", ""),
            })
    return jsonify({"error": "Player not found"}), 404


@ma_bp.route("/api/ma/volume", methods=["POST"])
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


# --- Queue endpoints ---


@ma_bp.route("/api/ma/queue")
def ma_queue():
    """Get active player queue from Music Assistant for track position."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500

    active_q = _fetch_active_queue()
    if active_q is None:
        return jsonify({"error": "MA unreachable"}), 500
    if not active_q:
        return jsonify({"elapsed_time": 0, "duration": 0, "name": ""})

    try:
        current_item = active_q.get("current_item") or {}
        next_item = active_q.get("next_item") or {}
        stream_details = current_item.get("streamdetails") or {}
        audio_fmt = stream_details.get("audio_format") or {}
        media_item = current_item.get("media_item") or {}
        meta = media_item.get("metadata") or {}

        quality, codec, codec_type, sample_rate, bits = _parse_queue_quality(audio_fmt)

        images = meta.get("images") or []
        image_url = ""
        for img in images:
            if img.get("type") == "thumb" and img.get("path"):
                image_url = img["path"]
                break
        if not image_url and images:
            image_url = images[0].get("path", "")

        lyrics = ""
        track_id = media_item.get("item_id")
        track_uri = media_item.get("uri", "")
        if track_id and track_uri:
            lyrics = _fetch_lyrics(track_id, track_uri)

        return jsonify({
            "elapsed_time": active_q.get("elapsed_time", 0),
            "elapsed_time_last_updated": active_q.get("elapsed_time_last_updated", 0),
            "duration": current_item.get("duration", 0),
            "name": current_item.get("name", ""),
            "uri": media_item.get("uri", ""),
            "server_time": time.time(),
            "next_track": next_item.get("name", ""),
            "next_duration": next_item.get("duration", 0),
            "quality": quality,
            "codec": codec_type or codec,
            "sample_rate": sample_rate,
            "bit_depth": bits,
            "queue_id": active_q.get("queue_id", ""),
            "queue_index": active_q.get("current_index", 0),
            "queue_total": active_q.get("items", 0),
            "shuffle": active_q.get("shuffle_enabled", False),
            "repeat": active_q.get("repeat_mode", "off"),
            "target_loudness": stream_details.get("target_loudness"),
            "popularity": meta.get("popularity"),
            "lyrics": lyrics,
            "image_url": image_url,
        })
    except (KeyError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 500


@ma_bp.route("/api/ma/queue/items")
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
        media_item = item.get("media_item") or {}
        artists = media_item.get("artists") or []
        artist_name = artists[0].get("name", "") if artists else ""
        name = item.get("name", "")
        items.append({
            "queue_item_id": item.get("queue_item_id", ""),
            "name": name,
            "duration": item.get("duration", 0),
            "sort_index": item.get("sort_index", 0),
            "artist": artist_name,
            "uri": media_item.get("uri", ""),
        })
    return jsonify({"items": items})


@ma_bp.route("/api/ma/queue/action", methods=["POST"])
def ma_queue_action():
    """Perform queue action: delete, move, play_index, clear, shuffle, repeat."""
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


# --- Image proxy ---


@ma_bp.route("/api/ma/imageproxy")
def ma_imageproxy():
    """Proxy album art images from MA to avoid CORS issues."""
    url = request.args.get("url", "")
    if not url:
        return "", 400
    proxy_url = (
        f"http://{SNAPCAST_SERVER}:8095/imageproxy"
        f"?path={urllib.request.quote(url, safe='')}"
        f"&size=512&fmt=jpeg"
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


# --- Favorites ---


@ma_bp.route("/api/ma/favorite", methods=["POST"])
def ma_favorite():
    """Add or remove a track from MA favorites."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500
    uri = (request.json or {}).get("uri", "")
    if not uri:
        return jsonify({"error": "Missing uri"}), 400
    result = ma_rpc("music/favorites/add_item", {"item": uri})
    return jsonify({"result": result or "ok"})


# --- Recently Played ---


@ma_bp.route("/api/ma/recent")
def ma_recent():
    """Get recently played items from MA."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500
    limit = int(request.args.get("limit", "20"))
    data = ma_rpc("music/recently_played_items", {
        "limit": limit, "media_types": ["track"],
    })
    if data is None:
        return jsonify({"error": "MA unreachable"}), 500
    result = data.get("result", data) if isinstance(data, dict) else data
    items = []
    for item in (result if isinstance(result, list) else []):
        media_item = item if "name" in item else item.get("media_item", item)
        artists = media_item.get("artists") or []
        artist_name = ", ".join(a.get("name", "") for a in artists) if artists else ""
        images = (media_item.get("metadata") or {}).get("images") or []
        thumb = ""
        for img in images:
            if img.get("type") == "thumb" and img.get("path"):
                thumb = img["path"]
                break
        if not thumb and images:
            thumb = images[0].get("path", "")
        items.append({
            "name": media_item.get("name", ""),
            "artist": artist_name,
            "uri": media_item.get("uri", ""),
            "duration": media_item.get("duration", 0),
            "image_url": thumb,
        })
    return jsonify({"items": items})


# --- Search ---


@ma_bp.route("/api/ma/search")
def ma_search():
    """Search MA library for tracks, albums, playlists."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Missing query"}), 400
    media_types = request.args.get("types", "track,album,playlist").split(",")
    limit = int(request.args.get("limit", "20"))
    data = ma_rpc("music/search", {
        "search_query": query,
        "media_types": [t.strip() for t in media_types],
        "limit": limit,
    })
    if data is None:
        return jsonify({"error": "MA unreachable"}), 500
    result = data.get("result", data) if isinstance(data, dict) else data
    if not isinstance(result, dict):
        return jsonify({"tracks": [], "albums": [], "playlists": []})

    def _parse_items(items, kind):
        out = []
        for item in (items or []):
            artists = item.get("artists") or []
            artist_name = ", ".join(a.get("name", "") for a in artists) if artists else ""
            images = (item.get("metadata") or {}).get("images") or []
            thumb = ""
            for img in images:
                if img.get("path"):
                    thumb = img["path"]
                    break
            out.append({
                "name": item.get("name", ""),
                "artist": artist_name,
                "uri": item.get("uri", ""),
                "duration": item.get("duration", 0),
                "image_url": thumb,
                "type": kind,
            })
        return out

    return jsonify({
        "tracks": _parse_items(result.get("tracks"), "track"),
        "albums": _parse_items(result.get("albums"), "album"),
        "playlists": _parse_items(result.get("playlists"), "playlist"),
    })


# --- Play media (enqueue URI) ---


@ma_bp.route("/api/ma/play", methods=["POST"])
def ma_play():
    """Play a media URI on the active queue."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500
    body = request.json or {}
    uri = body.get("uri", "")
    queue_id = body.get("queue_id", "")
    option = body.get("option", "play")  # play, next, add, replace
    if not uri or not queue_id:
        return jsonify({"error": "Missing uri or queue_id"}), 400
    result = ma_rpc("player_queues/play_media", {
        "queue_id": queue_id,
        "media": [uri],
        "option": option,
    })
    return jsonify({"result": result or "ok"})


# --- Playlists ---


@ma_bp.route("/api/ma/playlists")
def ma_playlists():
    """List all playlists from MA library."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500
    data = ma_rpc("music/playlists/library_items", {
        "limit": 100, "offset": 0,
    })
    if data is None:
        return jsonify({"error": "MA unreachable"}), 500
    result = data.get("result", data) if isinstance(data, dict) else data
    items = []
    for item in (result if isinstance(result, list) else []):
        items.append({
            "name": item.get("name", ""),
            "uri": item.get("uri", ""),
            "item_id": item.get("item_id", ""),
            "owner": item.get("owner", ""),
            "is_editable": item.get("is_editable", False),
        })
    return jsonify({"items": items})



# --- Album tracks ---


@ma_bp.route("/api/ma/album/tracks")
def ma_album_tracks():
    """Get tracks for an album."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500
    item_id = request.args.get("item_id", "")
    provider = request.args.get("provider", "library")
    if not item_id:
        return jsonify({"error": "Missing item_id"}), 400
    data = ma_rpc("music/albums/album_tracks", {
        "item_id": item_id,
        "provider_instance_id_or_domain": provider,
    })
    if data is None:
        return jsonify({"error": "MA unreachable"}), 500
    result = data.get("result", data) if isinstance(data, dict) else data
    items = []
    for item in (result if isinstance(result, list) else []):
        artists = item.get("artists") or []
        artist_name = ", ".join(a.get("name", "") for a in artists) if artists else ""
        items.append({
            "name": item.get("name", ""),
            "artist": artist_name,
            "uri": item.get("uri", ""),
            "duration": item.get("duration", 0),
            "track_number": item.get("track_number", 0),
        })
    items.sort(key=lambda x: x["track_number"])
    return jsonify({"items": items})



# --- Playlist tracks ---


@ma_bp.route("/api/ma/playlist/tracks")
def ma_playlist_tracks():
    """Get tracks for a playlist."""
    if not MA_TOKEN:
        return jsonify({"error": "MA_TOKEN not configured"}), 500
    item_id = request.args.get("item_id", "")
    provider = request.args.get("provider", "builtin")
    if not item_id:
        return jsonify({"error": "Missing item_id"}), 400
    data = ma_rpc("music/playlists/playlist_tracks", {
        "item_id": item_id,
        "provider_instance_id_or_domain": provider,
    })
    if data is None:
        return jsonify({"error": "MA unreachable"}), 500
    result = data.get("result", data) if isinstance(data, dict) else data
    items = []
    for i, item in enumerate(result if isinstance(result, list) else []):
        artists = item.get("artists") or []
        artist_name = ", ".join(a.get("name", "") for a in artists) if artists else ""
        items.append({
            "name": item.get("name", ""),
            "artist": artist_name,
            "uri": item.get("uri", ""),
            "duration": item.get("duration", 0),
            "track_number": i + 1,
        })
    return jsonify({"items": items})
