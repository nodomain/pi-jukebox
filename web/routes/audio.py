"""Audio (PipeWire) API blueprint for Jukebox Pi.

Endpoints:
    GET  /api/audio/status — list PipeWire sinks and default sink
    POST /api/audio/volume — set default sink volume
"""

import re

from flask import Blueprint, jsonify, request  # pylint: disable=import-error

from helpers import run_pw  # pylint: disable=import-error

audio_bp = Blueprint("audio", __name__)


def audio_status_data():
    """Collect PipeWire audio status as a dict (no Flask response)."""
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
            match = re.match(
                r"\s*[│├└─\s]*(\*?)\s*(\d+)\.\s+(.+?)"
                r"(?:\s+\[vol:\s*([\d.]+)\])?$",
                line,
            )
            if match:
                is_default = match.group(1) == "*"
                sink = {
                    "id": int(match.group(2)),
                    "name": match.group(3).strip(),
                    "volume": float(match.group(4)) if match.group(4) else None,
                    "default": is_default,
                }
                sinks.append(sink)
                if is_default:
                    default_sink = sink["name"]
    return {"sinks": sinks, "default_sink": default_sink}


@audio_bp.route("/api/audio/status")
def audio_status():
    """Return PipeWire audio sinks and default sink."""
    return jsonify(audio_status_data())


@audio_bp.route("/api/audio/volume", methods=["POST"])
def audio_volume():
    """Set PipeWire default sink volume."""
    vol = request.json.get("volume")
    if vol is None:
        return jsonify({"error": "Missing volume"}), 400
    vol = max(0.0, min(1.5, float(vol)))
    run_pw(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {vol}")
    return jsonify({"volume": vol})
