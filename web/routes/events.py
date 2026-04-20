"""Unified SSE event stream for Jukebox Pi.

Combines Music Assistant WebSocket events with periodic system stats
into a single SSE endpoint, eliminating most client-side polling.

Endpoints:
    GET /api/events — unified SSE stream

Event types pushed to clients:
    queue_updated       — MA queue state changed (from WS)
    queue_items_updated — MA queue items changed (from WS)
    queue_time_updated  — MA playback position (from WS)
    player_updated      — MA player state changed (from WS)
    connected           — MA WS connection status
    stats               — system metrics (temp, CPU, mem, WiFi, SD writes)
    bt_status           — Bluetooth connection, codec, AVRCP volume
    audio_status        — PipeWire sinks and default volume
    snapcast_status     — Snapcast clients, streams, now playing, controls
"""

import json
import logging
import queue
import threading
import time

from flask import Blueprint, Response  # pylint: disable=import-error

_log = logging.getLogger(__name__)

events_bp = Blueprint("events", __name__)

# SSE subscribers: list of queue.Queue objects
_clients = []
_clients_lock = threading.Lock()


def broadcast(event_type, data):
    """Send an SSE event to all connected browsers.

    Args:
        event_type: SSE event name string.
        data: Dict to JSON-serialize as event data.
    """
    msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    with _clients_lock:
        dead = []
        for client_q in _clients:
            try:
                client_q.put_nowait(msg)
            except queue.Full:
                dead.append(client_q)
        for client_q in dead:
            _clients.remove(client_q)


def _has_clients():
    """Check if any SSE clients are connected."""
    with _clients_lock:
        return len(_clients) > 0


def _poll_loop():
    """Background thread: periodically collect system data and broadcast."""
    # Import here to avoid circular imports at module level
    from routes.system import stats_data  # pylint: disable=import-outside-toplevel
    from routes.bluetooth import bt_status_data  # pylint: disable=import-outside-toplevel
    from routes.audio import audio_status_data  # pylint: disable=import-outside-toplevel
    from routes.snapcast import snapcast_status_data  # pylint: disable=import-outside-toplevel

    tick = 0
    while True:
        time.sleep(3)
        if not _has_clients():
            continue
        tick += 1

        # Stats every 3s
        try:
            broadcast("stats", stats_data())
        except (OSError, ValueError):
            pass

        # BT + audio + snapcast every 9s (every 3rd tick)
        if tick % 3 == 0:
            try:
                broadcast("bt_status", bt_status_data())
            except (OSError, ValueError):
                pass
            try:
                broadcast("audio_status", audio_status_data())
            except (OSError, ValueError):
                pass
            try:
                broadcast("snapcast_status", snapcast_status_data())
            except (OSError, ValueError):
                pass


def start_poll_thread():
    """Start the background polling thread."""
    thread = threading.Thread(target=_poll_loop, daemon=True)
    thread.start()
    _log.info("SSE poll thread started")


@events_bp.route("/api/events")
def unified_events():
    """Unified SSE endpoint: streams all events to the browser."""
    def stream():
        client_q = queue.Queue(maxsize=50)
        with _clients_lock:
            _clients.append(client_q)
        try:
            while True:
                try:
                    msg = client_q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _clients_lock:
                if client_q in _clients:
                    _clients.remove(client_q)

    return Response(
        stream(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
