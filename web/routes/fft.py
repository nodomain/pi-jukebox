"""FFT visualizer (cava) SSE blueprint for Jukebox Pi.

Manages an on-demand cava process: starts when the first browser connects,
stops when the last disconnects.

Endpoints:
    GET /api/fft/stream — SSE stream of cava FFT bar data
"""

import logging
import os
import queue
import subprocess
import threading

from flask import Blueprint, Response  # pylint: disable=import-error

fft_bp = Blueprint("fft", __name__)

CAVA_CONF = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cava.conf")
_log = logging.getLogger(__name__)

CAVA_CONF = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cava.conf")

# Shared cava process state
_cava_lock = threading.Lock()
_cava_proc: subprocess.Popen | None = None  # type: ignore[type-arg]
_cava_clients: list = []


def _cava_reader():
    """Background thread: read cava stdout and broadcast to SSE clients."""
    try:
        assert _cava_proc is not None and _cava_proc.stdout is not None
        for line in _cava_proc.stdout:
            line = line.strip()
            if not line:
                continue
            msg = f"data: {line}\n\n"
            with _cava_lock:
                dead = []
                for client_q in _cava_clients:
                    try:
                        client_q.put_nowait(msg)
                    except queue.Full:
                        dead.append(client_q)
                for client_q in dead:
                    _cava_clients.remove(client_q)
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
        thread = threading.Thread(target=_cava_reader, daemon=True)
        thread.start()
        _log.info("cava started (pid %d)", _cava_proc.pid)
    except OSError as exc:
        _log.warning("cava failed to start: %s", exc)


def _cava_stop():
    """Stop the shared cava process if no clients remain."""
    global _cava_proc  # pylint: disable=global-statement
    if _cava_proc is None:
        return
    if _cava_proc.poll() is None:
        _cava_proc.terminate()
        _log.info("cava stopped")
    _cava_proc = None


@fft_bp.route("/api/fft/stream")
def fft_stream():
    """SSE endpoint: stream cava FFT data to browser."""
    def stream():
        client_q = queue.Queue(maxsize=30)
        with _cava_lock:
            _cava_clients.append(client_q)
            _cava_start()
        try:
            while True:
                try:
                    msg = client_q.get(timeout=30)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _cava_lock:
                if client_q in _cava_clients:
                    _cava_clients.remove(client_q)
                if not _cava_clients:
                    _cava_stop()

    return Response(
        stream(), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
