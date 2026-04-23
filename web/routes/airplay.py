"""AirPlay metadata reader for Jukebox Pi.

Reads the shairport-sync metadata pipe, parses track info and cover art,
and exposes current AirPlay state via an API endpoint.

Shairport-sync metadata pipe format:
    Each item is an XML element like:
        <item><type>...</type><code>...</code><length>N</length>
        <data encoding="base64">...</data></item>

Key codes we care about (ASCII hex of 4-char codes):
    ssnc/mdst — metadata bundle start
    core/minm — track title
    core/asar — artist
    core/asal — album
    ssnc/PICT — cover art (binary image data)
    ssnc/prgr — progress (start/current/end in RTP timestamps)
    ssnc/pbeg — play begin
    ssnc/pend — play end

Endpoint:
    GET /api/airplay/status — current AirPlay now-playing state
"""

import base64
import logging
import os
import re
import sys
import threading
import time

from flask import Blueprint, Response, jsonify  # pylint: disable=import-error

_log = logging.getLogger(__name__)
_log.setLevel(logging.INFO)
if not _log.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[airplay] %(message)s"))
    _log.addHandler(_h)
    _log.propagate = False

airplay_bp = Blueprint("airplay", __name__)

PIPE_PATH = "/tmp/shairport-sync-metadata"

# Shared state updated by reader thread, read by API
_state = {
    "active": False,
    "title": "",
    "artist": "",
    "album": "",
    "cover": None,  # raw image bytes
    "cover_mime": "image/jpeg",
    "started_at": 0,
    "ended_at": 0,
    "lock": threading.Lock(),
}


def _hex_code(four_chars):
    """Convert a 4-char type/code like 'ssnc' to the XML hex string '73736e63'."""
    return four_chars.encode("ascii").hex()


# Pre-compute code lookups
CODE_TITLE = _hex_code("minm")
CODE_ARTIST = _hex_code("asar")
CODE_ALBUM = _hex_code("asal")
CODE_PICT = _hex_code("PICT")
CODE_PBEG = _hex_code("pbeg")
CODE_PEND = _hex_code("pend")
CODE_PFLS = _hex_code("pfls")  # pause/flush
CODE_PRSM = _hex_code("prsm")  # resume

ITEM_RE = re.compile(
    rb"<item>\s*<type>([0-9a-f]+)</type>\s*<code>([0-9a-f]+)</code>\s*"
    rb"<length>(\d+)</length>\s*"
    rb"(?:<data encoding=\"base64\">\s*([^<]*)\s*</data>\s*)?"
    rb"</item>",
    re.DOTALL,
)


def _decode(data_b64):
    """Decode base64 data to bytes, or empty bytes on failure."""
    if not data_b64:
        return b""
    try:
        return base64.b64decode(data_b64)
    except (ValueError, TypeError):
        return b""


def _reader_loop():
    """Background thread: read metadata pipe and update state."""
    buffer = b""
    while True:
        try:
            # Non-blocking open so we can retry if shairport-sync isn't running yet
            fd = os.open(PIPE_PATH, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd, "rb", buffering=0) as pipe:
                while True:
                    try:
                        chunk = pipe.read(8192)
                    except BlockingIOError:
                        time.sleep(0.1)
                        continue
                    if chunk is None:
                        time.sleep(0.1)
                        continue
                    if not chunk:
                        # Writer closed, reopen
                        time.sleep(0.5)
                        break
                    buffer += chunk
                    # Process all complete <item>...</item> blocks in buffer
                    while True:
                        match = ITEM_RE.search(buffer)
                        if not match:
                            break
                        _, code, _, data_b64 = match.groups()
                        code_str = code.decode("ascii")
                        _handle_item(code_str, _decode(data_b64))
                        buffer = buffer[match.end():]
                    # Guard against unbounded growth on malformed input
                    if len(buffer) > 1_000_000:
                        buffer = b""
        except FileNotFoundError:
            _log.warning("Metadata pipe %s not found, retrying", PIPE_PATH)
            time.sleep(5)
        except Exception as exc:  # pylint: disable=broad-except
            _log.warning("AirPlay metadata reader error: %s", exc)
            time.sleep(2)


def _handle_item(code, data):
    """Update shared state based on a single metadata item."""
    if code == CODE_TITLE:
        with _state["lock"]:
            _state["title"] = data.decode("utf-8", errors="replace")
    elif code == CODE_ARTIST:
        with _state["lock"]:
            _state["artist"] = data.decode("utf-8", errors="replace")
    elif code == CODE_ALBUM:
        with _state["lock"]:
            _state["album"] = data.decode("utf-8", errors="replace")
    elif code == CODE_PICT:
        # Empty PICT (len=0) means "no cover available" — keep old cover
        if not data:
            return
        with _state["lock"]:
            _state["cover"] = data
            # Detect mime from magic bytes
            if data[:3] == b"\xff\xd8\xff":
                _state["cover_mime"] = "image/jpeg"
            elif data[:8] == b"\x89PNG\r\n\x1a\n":
                _state["cover_mime"] = "image/png"
    elif code == CODE_PBEG or code == CODE_PRSM:
        with _state["lock"]:
            _state["active"] = True
            _state["ended_at"] = 0
            if not _state["started_at"]:
                _state["started_at"] = time.time()
    elif code == CODE_PEND or code == CODE_PFLS:
        # Don't immediately mark as inactive — iPhone sends pend/pbeg between tracks.
        # Store the end timestamp so /status can decide based on age.
        with _state["lock"]:
            _state["ended_at"] = time.time()


def start_airplay_thread():
    """Start the metadata pipe reader thread."""
    if not os.path.exists(PIPE_PATH):
        _log.info("Metadata pipe %s not present, AirPlay metadata disabled", PIPE_PATH)
        return
    thread = threading.Thread(target=_reader_loop, daemon=True)
    thread.start()


def is_active():
    """Return True if AirPlay is currently playing (for other routes to check)."""
    return os.path.exists("/run/jukebox-airplay-active")


@airplay_bp.route("/api/airplay/status")
def airplay_status():
    """Return current AirPlay now-playing state."""
    # The airplay-begin hook creates this file, airplay-end removes it.
    # This is the most reliable signal for "AirPlay is playing right now".
    lock_exists = os.path.exists("/run/jukebox-airplay-active")
    with _state["lock"]:
        return jsonify({
            "active": lock_exists,
            "title": _state["title"],
            "artist": _state["artist"],
            "album": _state["album"],
            "has_cover": _state["cover"] is not None,
            "started_at": _state["started_at"],
        })


@airplay_bp.route("/api/airplay/cover")
def airplay_cover():
    """Return the current AirPlay cover art image."""
    with _state["lock"]:
        cover = _state["cover"]
        mime = _state["cover_mime"]
    if not cover:
        return "", 404
    return Response(cover, mimetype=mime, headers={"Cache-Control": "no-cache"})
