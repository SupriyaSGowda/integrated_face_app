#!/usr/bin/env python

# make sure logic package is available when script is launched from subdirectory
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import threading
import cv2
import time
from flask import Flask, jsonify, Response
from flask_cors import CORS
from logic import track_room

app = Flask(__name__)
CORS(app, origins=["http://localhost:5173"], supports_credentials=True)

monitor_thread = None


# =========================
# HELPER
# =========================
def is_monitoring_running():
    return monitor_thread is not None and monitor_thread.is_alive()


def start_monitoring_thread():
    global monitor_thread

    if is_monitoring_running():
        return

    print("🔥 Starting monitoring thread...")

    def safe_runner():
        try:
            track_room.track_room()
        except Exception as e:
            print("❌ TRACK ROOM CRASHED:", e)

    monitor_thread = threading.Thread(
        target=safe_runner,
        daemon=True
    )
    monitor_thread.start()


# =========================
# STATUS
# =========================
@app.route("/status", methods=["GET"])
def get_status():
    return jsonify({
        "monitoring": is_monitoring_running(),
        "totalInside": len(track_room.present_people),
        "lastEntryDetection": track_room.last_entry_detection,
        "lastExitDetection": track_room.last_exit_detection
    })


# =========================
# PEOPLE LIST
# =========================
DEFAULT_PEOPLE = ["Hrithik", "Supriya", "Anirudh", "Meenakshi"]

@app.route("/people", methods=["GET"])
def get_people():
    names = (
        set(DEFAULT_PEOPLE)
        | set(track_room.entry_times.keys())
        | set(track_room.exit_times.keys())
        | set(track_room.present_people)
    )

    people_list = []

    for name in sorted(names):
        status = "inside" if name in track_room.present_people else "outside"

        people_list.append({
            "name": name,
            "status": status,
            "lastEntry": track_room.entry_times.get(name),
            "lastExit": track_room.exit_times.get(name)
        })

    return jsonify(people_list)


# =========================
# ACTIVITY LOG
# =========================
@app.route("/activity", methods=["GET"])
def get_activity():
    return jsonify(list(track_room.activity_log))


# =========================
# ENTRY CAMERA STREAM
# =========================
@app.route("/video_feed_entry")
def video_feed_entry():
    return Response(
        generate_entry_stream(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


def generate_entry_stream():
    while True:
        frame = track_room.latest_frame_entry

        if frame is None:
            time.sleep(0.01)
            continue

        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' +
               buffer.tobytes() + b'\r\n')

        time.sleep(0.03)


# =========================
# EXIT CAMERA STREAM
# =========================
@app.route("/video_feed_exit")
def video_feed_exit():
    return Response(
        generate_exit_stream(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


def generate_exit_stream():
    while True:
        frame = track_room.latest_frame_exit

        if frame is None:
            time.sleep(0.01)
            continue

        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' +
               buffer.tobytes() + b'\r\n')

        time.sleep(0.03)


# =========================
# HEALTH
# =========================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "OK",
        "monitoring": is_monitoring_running()
    })


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Control room tracker HTTP server")
    parser.add_argument("--port", type=int, default=5003,
                        help="port to bind the Flask app")
    args = parser.parse_args()

    # 🔥 AUTO START MONITORING WHEN PROCESS BOOTS
    start_monitoring_thread()

    # Give it a second to initialize
    time.sleep(2)

    print(f"🚀 Flask Server Running on http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)