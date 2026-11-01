"""Sound effects (SFX) API blueprint for Jukebox Pi.

Plays short local audio clips directly into PipeWire with pw-play, bypassing
Snapcast. No 500 ms Snapcast buffer, so a clip starts within a few hundred ms
and mixes on top of whatever music is currently playing.

Clips live in packs: one subdirectory per pack under web/sfx/ (deployed to
/opt/jukebox/sfx/ on the Pi).

Endpoints:
    GET      /api/sfx            list packs and their clips
    GET|POST /api/sfx/play       play a clip (fire-and-forget)
        pack=<name>      required, e.g. "halloween"
        clip=<filename>  optional, random clip of the pack if omitted
        volume=<0..1.5>  optional pw-play stream volume, default 1.0

Random picks use a shuffle bag per pack: every clip plays once before any
clip repeats, and a new round never starts with the clip that just played.
"""

import os
import random
import subprocess  # pylint: disable=import-error
import threading

from flask import Blueprint, jsonify, request  # pylint: disable=import-error

sfx_bp = Blueprint("sfx", __name__)

SFX_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sfx")
_AUDIO_EXT = (".mp3", ".wav", ".ogg", ".flac")

_lock = threading.Lock()
_current = {"proc": None}
_bags = {}   # pack -> remaining clips of the current shuffle round
_last = {}   # pack -> last clip played


def _next_random(pack, clips):
    """Draw the next clip from the pack's shuffle bag (caller holds _lock)."""
    bag = [c for c in _bags.get(pack, []) if c in clips]
    if not bag:
        bag = list(clips)
        random.shuffle(bag)
        # Avoid an immediate repeat across the round boundary
        if len(bag) > 1 and bag[-1] == _last.get(pack):
            bag[0], bag[-1] = bag[-1], bag[0]
    clip = bag.pop()
    _bags[pack] = bag
    return clip


def _packs():
    """Return {pack_name: [clip filenames]} for every pack directory."""
    packs = {}
    if not os.path.isdir(SFX_DIR):
        return packs
    for name in sorted(os.listdir(SFX_DIR)):
        path = os.path.join(SFX_DIR, name)
        if os.path.isdir(path):
            packs[name] = sorted(
                f for f in os.listdir(path) if f.lower().endswith(_AUDIO_EXT)
            )
    return packs


@sfx_bp.route("/api/sfx")
def sfx_list():
    """List all SFX packs and their clips."""
    return jsonify(_packs())


@sfx_bp.route("/api/sfx/play", methods=["GET", "POST"])
def sfx_play():
    """Play a (random) clip of a pack on the default PipeWire sink."""
    params = request.values
    pack = params.get("pack", "")
    clips = _packs().get(pack)
    if not clips:
        return jsonify({"error": f"Unknown or empty pack: {pack}"}), 404

    requested = params.get("clip")
    # Only filenames from the pack listing are accepted (no path traversal)
    if requested and requested not in clips:
        return jsonify({"error": f"Unknown clip: {requested}"}), 404

    try:
        volume = max(0.0, min(1.5, float(params.get("volume", 1.0))))
    except ValueError:
        return jsonify({"error": "Invalid volume"}), 400

    env = dict(os.environ, XDG_RUNTIME_DIR="/run/user/1000")
    with _lock:
        clip = requested or _next_random(pack, clips)
        _last[pack] = clip
        # Cut off a still-running clip so rapid triggers do not stack up
        prev = _current["proc"]
        if prev is not None and prev.poll() is None:
            prev.terminate()
        _current["proc"] = subprocess.Popen(  # pylint: disable=consider-using-with
            [
                "pw-play",
                "--media-role=Notification",
                f"--volume={volume}",
                os.path.join(SFX_DIR, pack, clip),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return jsonify({"pack": pack, "clip": clip, "volume": volume})
