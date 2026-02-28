#!/usr/bin/env python

# make sure logic package is available when script is launched from subdirectory
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import threading
import cv2
from flask import Flask, jsonify, Response
from flask_cors import CORS
from logic import track_room

app = Flask(__name__)
CORS(app, origins=["http://localhost:5173"], supports_credentials=True)

monitor_thread = None


# =========================
# START MONITORING
# =========================
@app.route("/start", methods=["POST", "GET"])
def start_monitoring():
    global monitor_thread

    if monitor_thread is None or not monitor_thread.is_alive():
        monitor_thread = threading.Thread(
            target=track_room.track_room,
            daemon=True
        )
        monitor_thread.start()

        return jsonify({
            "success": True,
            "message": "Monitoring started"
        })

    return jsonify({
        "success": False,
        "message": "Already running"
    }), 409


# =========================
# STATUS
# =========================
@app.route("/status", methods=["GET"])
def get_status():
    return jsonify({
        "monitoring": monitor_thread is not None and monitor_thread.is_alive(),
        "totalInside": len(track_room.present_people),
        "lastEntryDetection": track_room.last_entry_detection,
        "lastExitDetection": track_room.last_exit_detection
    })


# =====================================================
# Known people (defaults, can be extended by recognitions)
# =====================================================
DEFAULT_PEOPLE = ["Hrithik", "Supriya", "Anirudh", "Meenakshi"]

# =========================
# PEOPLE LIST
# =========================
@app.route("/people", methods=["GET"])
def get_people():
    # start with the default roster but merge in any names that have been
    # seen by the tracker (entry/exit timestamps or currently present).
    names = set(DEFAULT_PEOPLE) | set(track_room.entry_times.keys()) | set(track_room.exit_times.keys()) | set(track_room.present_people)

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
    # return a copy so the list can still be mutated by the tracker thread
    return jsonify(list(track_room.activity_log))


# =========================
# ENTRY CAMERA STREAM
# =========================
@app.route("/video_feed_entry")
def video_feed_entry():
    return Response(generate_entry_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


def generate_entry_stream():
    import time

    while True:
        frame = track_room.latest_frame_entry

        if frame is None:
            time.sleep(0.01)
            continue

        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            time.sleep(0.01)
            continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' +
               buffer.tobytes() + b'\r\n')

        time.sleep(0.03)   # ~30 FPS cap


# =========================
# EXIT CAMERA STREAM
# =========================
@app.route("/video_feed_exit")
def video_feed_exit():
    return Response(generate_exit_stream(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


def generate_exit_stream():
    import time

    while True:
        frame = track_room.latest_frame_exit

        if frame is None:
            time.sleep(0.01)
            continue

        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            time.sleep(0.01)
            continue

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' +
               buffer.tobytes() + b'\r\n')

        time.sleep(0.03)

# =========================
# STOP (Still placeholder)
# =========================
@app.route("/stop", methods=["POST"])
def stop_monitoring():
    # thread cannot be cleanly terminated at the moment
    return jsonify({
        "success": True,
        "message": "Stop request received (thread continues to run)"
    })


# =========================
# HEALTH
# =========================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "OK"
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

    print(f"🚀 Flask Server Running on http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=False, threaded=True)