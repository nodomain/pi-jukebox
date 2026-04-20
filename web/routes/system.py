"""System stats and service control blueprint for Jukebox Pi.

Endpoints:
    GET  /api/stats            — system metrics (temp, CPU, mem, WiFi, etc.)
    POST /api/service/<action> — restart services or reboot
"""

import re

from flask import Blueprint, jsonify  # pylint: disable=import-error

from helpers import run  # pylint: disable=import-error

system_bp = Blueprint("system", __name__)


def decode_throttle(val):
    """Decode vcgencmd get_throttled value into flags.

    Args:
        val: Hex string or integer throttle value.

    Returns:
        Dict of boolean throttle flags.
    """
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


def _parse_wifi():
    """Parse WiFi stats from iw and /proc/net/dev."""
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

    net = run("cat /proc/net/dev | grep wlan0").split()
    if len(net) > 9:
        wifi["rx_bytes"] = int(net[1])
        wifi["tx_bytes"] = int(net[9])
        wifi["rx_packets"] = int(net[2])
        wifi["tx_packets"] = int(net[10])
    return wifi


def stats_data():
    """Collect system stats as a dict (no Flask response)."""
    temp = run("vcgencmd measure_temp").replace("temp=", "").replace("'C", "")
    uptime_raw = run("cat /proc/uptime").split()[0]
    load = run("cat /proc/loadavg").split()[:3]

    meminfo = run("cat /proc/meminfo")
    mem = {}
    for line in meminfo.splitlines():
        parts = line.split()
        if parts[0] in ("MemTotal:", "MemAvailable:"):
            mem[parts[0].rstrip(":")] = int(parts[1])
    mem_used = mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)
    mem_total = mem.get("MemTotal", 0)

    cpu_freq_raw = run("vcgencmd measure_clock arm")
    cpu_freq = 0
    match = re.search(r"=(\d+)", cpu_freq_raw)
    if match:
        cpu_freq = int(match.group(1)) / 1_000_000

    wifi = _parse_wifi()

    diskstats = run("cat /proc/diskstats | grep 'mmcblk0 '")
    sd_writes = 0
    if diskstats:
        parts = diskstats.split()
        if len(parts) > 7:
            sd_writes = int(parts[7])

    throttle_raw = run("vcgencmd get_throttled").replace("throttled=", "")
    throttle = decode_throttle(throttle_raw)
    throttle["raw"] = throttle_raw

    return {
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


@system_bp.route("/api/stats")
def stats():
    """Return system stats: temp, CPU, memory, WiFi, SD writes, throttle."""
    return jsonify(stats_data())


# --- Service Control ---


@system_bp.route("/api/service/<action>", methods=["POST"])
def service_control(action):
    """Restart services or reboot the Pi."""
    if action == "restart-snapclient":
        run("sudo systemctl restart snapclient")
        return jsonify({"result": "ok"})
    if action == "restart-bt":
        run("sudo systemctl restart bt-autoconnect")
        return jsonify({"result": "ok"})
    if action == "reboot":
        run("sudo reboot &")
        return jsonify({"result": "rebooting"})
    return jsonify({"error": "unknown action"}), 400
