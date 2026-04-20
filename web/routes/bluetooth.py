"""Bluetooth API blueprint for Jukebox Pi.

Endpoints:
    GET  /api/bt/status     — connection status, codec, AVRCP volume
    POST /api/bt/volume     — set AVRCP hardware volume (0-127)
    POST /api/bt/scan       — scan for nearby devices
    POST /api/bt/pair       — pair with a device by MAC
    POST /api/bt/connect    — connect to a paired device
    POST /api/bt/disconnect — disconnect a device
"""

import json
import re

from flask import Blueprint, jsonify, request  # pylint: disable=import-error

from helpers import run, run_pw  # pylint: disable=import-error

bt_bp = Blueprint("bluetooth", __name__)


def _find_bt_transport():
    """Find the active BlueZ MediaTransport1 D-Bus path."""
    raw = run("busctl tree org.bluez 2>/dev/null | grep '/fd'")
    for line in raw.splitlines():
        path = line.strip().lstrip("├─└─│ ")
        if "/fd" in path:
            return path
    return ""


def bt_status_data():
    """Collect Bluetooth status as a dict (no Flask response)."""
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

    return {
        "connected": connected, "name": name, "mac": mac,
        "codec": codec, "hw_volume": hw_volume,
    }


@bt_bp.route("/api/bt/status")
def bt_status():
    """Return Bluetooth connection status, codec, and AVRCP volume."""
    return jsonify(bt_status_data())


@bt_bp.route("/api/bt/volume", methods=["POST"])
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


@bt_bp.route("/api/bt/scan", methods=["POST"])
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


@bt_bp.route("/api/bt/pair", methods=["POST"])
def bt_pair():
    """Pair with a Bluetooth device by MAC address."""
    mac = request.json.get("mac", "")
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac):
        return jsonify({"error": "Invalid MAC"}), 400
    out = run(f"bluetoothctl pair {mac}", timeout=15)
    run(f"bluetoothctl trust {mac}")
    return jsonify({"result": out})


@bt_bp.route("/api/bt/connect", methods=["POST"])
def bt_connect():
    """Connect to a paired Bluetooth device."""
    mac = request.json.get("mac", "")
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac):
        return jsonify({"error": "Invalid MAC"}), 400
    out = run(f"bluetoothctl connect {mac}", timeout=10)
    return jsonify({"result": out, "success": "successful" in out.lower()})


@bt_bp.route("/api/bt/disconnect", methods=["POST"])
def bt_disconnect():
    """Disconnect a Bluetooth device."""
    mac = request.json.get("mac", "")
    if not re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", mac):
        return jsonify({"error": "Invalid MAC"}), 400
    out = run(f"bluetoothctl disconnect {mac}")
    return jsonify({"result": out})
