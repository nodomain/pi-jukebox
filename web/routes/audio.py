"""Audio (PipeWire) API blueprint for Jukebox Pi.

Endpoints:
    GET  /api/audio/status — list PipeWire sinks and default sink
    POST /api/audio/volume — set default sink volume
    GET  /api/audio/eq     — get current EQ preset
    POST /api/audio/eq     — set EQ preset (rewrites PipeWire filter-chain)
"""

import os
import re

from flask import Blueprint, jsonify, request  # pylint: disable=import-error

from helpers import run, run_pw  # pylint: disable=import-error

audio_bp = Blueprint("audio", __name__)

# Path to the PipeWire filter-chain config for EQ
_EQ_CONF = os.path.expanduser(
    "~/.config/pipewire/pipewire.conf.d/99-jukebox-eq.conf"
)


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


# --- EQ Presets ---

EQ_PRESETS = {
    "flat": {"bass": 0, "treble": 0, "label": "Flat"},
    "bass_boost": {"bass": 6, "treble": 0, "label": "Bass Boost"},
    "vocal": {"bass": -2, "treble": 3, "label": "Vocal"},
    "night": {"bass": -4, "treble": -2, "label": "Night Mode"},
}

# In-memory current preset (persisted per session)
_current_eq = {"preset": "flat", "bass": 0, "treble": 0}


@audio_bp.route("/api/audio/eq")
def audio_eq():
    """Get current EQ preset and available presets."""
    presets = []
    for key, val in EQ_PRESETS.items():
        presets.append({
            "id": key,
            "label": val["label"],
            "bass": val["bass"],
            "treble": val["treble"],
        })
    return jsonify({
        "current": _current_eq["preset"],
        "bass": _current_eq["bass"],
        "treble": _current_eq["treble"],
        "presets": presets,
    })


@audio_bp.route("/api/audio/eq", methods=["POST"])
def audio_eq_set():
    """Set EQ preset by writing a parametric EQ text file and restarting PipeWire."""
    body = request.json or {}
    preset = body.get("preset", "")
    if preset not in EQ_PRESETS:
        return jsonify({"error": f"Unknown preset: {preset}"}), 400
    vals = EQ_PRESETS[preset]
    _current_eq["preset"] = preset
    _current_eq["bass"] = vals["bass"]
    _current_eq["treble"] = vals["treble"]

    bass = float(vals["bass"])
    treble = float(vals["treble"])
    # Preamp compensates for boost to avoid clipping
    preamp = -max(abs(bass), abs(treble))

    # Write parametric EQ text file (read by libpipewire-module-parametric-equalizer)
    eq_txt = os.path.expanduser("~/.config/pipewire/jukebox-eq.txt")
    os.makedirs(os.path.dirname(eq_txt), exist_ok=True)
    with open(eq_txt, "w") as f:
        f.write(
            f"Preamp: {preamp:.1f} dB\n"
            f"Filter 1: ON LSC Fc 200 Hz Gain {bass:.1f} dB Q 0.707\n"
            f"Filter 2: ON HSC Fc 4000 Hz Gain {treble:.1f} dB Q 0.707\n"
        )

    # Restart pipewire to reload the EQ file, then snapclient to reconnect.
    # Brief ~3s audio gap is unavoidable (PipeWire limitation).
    run("systemctl --user restart pipewire", timeout=10)
    run("sleep 2 && sudo systemctl restart snapclient", timeout=15)

    return jsonify({
        "preset": preset,
        "bass": vals["bass"],
        "treble": vals["treble"],
    })

    return jsonify({
        "preset": preset,
        "bass": vals["bass"],
        "treble": vals["treble"],
    })
