#!/usr/bin/env python3
"""Jukebox Pi Web Dashboard.

Flask app factory: registers all blueprints and starts the Music Assistant
WebSocket relay thread.
"""

import sys
import os

# Ensure the web/ directory is on sys.path so helpers and routes are importable
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template  # pylint: disable=import-error

from routes.bluetooth import bt_bp
from routes.snapcast import snap_bp
from routes.ma import ma_bp, start_ws_thread
from routes.audio import audio_bp
from routes.system import system_bp
from routes.fft import fft_bp
from routes.events import events_bp, start_poll_thread
from routes.airplay import airplay_bp, start_airplay_thread

app = Flask(__name__)


# --- Register blueprints ---
app.register_blueprint(bt_bp)
app.register_blueprint(snap_bp)
app.register_blueprint(ma_bp)
app.register_blueprint(audio_bp)
app.register_blueprint(system_bp)
app.register_blueprint(fft_bp)
app.register_blueprint(events_bp)
app.register_blueprint(airplay_bp)


@app.route("/")
def index():
    """Serve the main dashboard page."""
    return render_template("index.html")


# Start background threads
start_ws_thread(app)
start_poll_thread()
start_airplay_thread()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
