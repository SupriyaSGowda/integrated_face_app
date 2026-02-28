# ensure logic package is importable
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, Response, jsonify
from flask_cors import CORS
import threading
import time
import json
from logic import detect

app = Flask(__name__)

# Allow Vite frontend
CORS(app, origins=["http://localhost:5173"])

# -------------------------
# Start Monitor Thread Once
# -------------------------
_monitor_started = False

def monitor_thread():
    detect.run_room_monitor(show_window=False)

def start_monitor():
    global _monitor_started
    if not _monitor_started:
        threading.Thread(target=monitor_thread, daemon=True).start()
        _monitor_started = True

@app.before_request
def _ensure_monitor():
    start_monitor()

# -------------------------
# MJPEG Video Stream
# -------------------------
def generate_frames():
    while True:
        if detect.current_frame_jpeg is not None:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + detect.current_frame_jpeg +
                b"\r\n"
            )
        time.sleep(0.1)

@app.route("/status")
def status():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

# -------------------------
# JSON Snapshot Endpoint
# -------------------------
@app.route("/status-json")
def status_json():
    ts = detect.last_update_time
    if ts is not None:
        ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))

    return jsonify(
        people=detect.person_count_global,
        status=detect.room_status_global,
        timestamp=ts,
    )

# -------------------------
# SSE Endpoint
# -------------------------
@app.route("/status-stream")
def status_stream():

    def event_generator():
        last_people = None
        last_status = None
        last_ts = None

        while True:
            people = detect.person_count_global
            status = detect.room_status_global
            ts = detect.last_update_time

            if ts is not None:
                ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))

            if (
                people != last_people or
                status != last_status or
                ts != last_ts
            ):
                data = {
                    "people": people,
                    "status": status,
                    "timestamp": ts,
                }

                yield f"data: {json.dumps(data)}\n\n"

                last_people = people
                last_status = status
                last_ts = ts

            time.sleep(0.5)

    response = Response(
        event_generator(),
        mimetype="text/event-stream"
    )

    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"

    return response

@app.route("/health")
def health():
    return jsonify(status="ok")

start_monitor()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="4‑people room status HTTP server")
    parser.add_argument("--port", type=int, default=5002,
                        help="port to bind the Flask app")
    args = parser.parse_args()

    app.run(host="0.0.0.0", port=args.port) 