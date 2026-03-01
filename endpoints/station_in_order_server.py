#!/usr/bin/env python3

# bring workspace root onto sys.path so the logic package can be imported
import os
import sys
import threading
import time
import signal
import argparse
from flask import Flask, Response, jsonify

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from logic import face_app

app = Flask(__name__)

# =========================================================
# GLOBAL STATE
# =========================================================
inference_thread = None
inference_lock = threading.Lock()
shutdown_event = threading.Event()


# =========================================================
# SAFE INFERENCE START
# =========================================================
def start_inference():
    global inference_thread

    with inference_lock:
        if inference_thread and inference_thread.is_alive():
            return

        def run_loop():
            print("🔥 Inference thread started")
            try:
                face_app.background_inference_loop()
            except Exception as e:
                print("❌ Inference crashed:", e)

        inference_thread = threading.Thread(
            target=run_loop,
            daemon=True
        )
        inference_thread.start()


# =========================================================
# CLEAN SHUTDOWN
# =========================================================
def graceful_shutdown(signum=None, frame=None):
    print("🛑 Station server shutting down...")
    shutdown_event.set()

    # If your face_app has a stop flag, trigger it here
    if hasattr(face_app, "STOP_EVENT"):
        face_app.STOP_EVENT.set()

    time.sleep(1)
    os._exit(0)


signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)


# =========================================================
# MJPEG STREAM
# =========================================================
def mjpeg_stream():
    last_frame = None

    while not shutdown_event.is_set():
        try:
            frame = face_app.get_last_frame_jpeg()

            if frame and frame != last_frame:
                last_frame = frame
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' +
                    frame +
                    b'\r\n'
                )

        except GeneratorExit:
            break
        except Exception as e:
            print("⚠ Stream error:", e)
            time.sleep(0.1)

        time.sleep(0.01)


@app.route("/video_feed")
def video_feed():
    return Response(
        mjpeg_stream(),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive"
        }
    )


# =========================================================
# ALERT API
# =========================================================
@app.route("/alerts")
def api_alerts():
    try:
        alerts = face_app.get_alerts()

        if alerts and hasattr(face_app, "_ALERT_LOCK"):
            with face_app._ALERT_LOCK:
                face_app.LAST_ALERTS.clear()

        return jsonify({
            "count": len(alerts),
            "alerts": alerts
        })

    except Exception as e:
        print("⚠ Alert API error:", e)
        return jsonify({"error": str(e)}), 500


# =========================================================
# STATUS API
# =========================================================
@app.route("/status")
def api_status():
    return jsonify({
        "status": "running",
        "inference_thread_alive": inference_thread.is_alive() if inference_thread else False,
        "num_cams": len(face_app.RTSP_URLS),
        "active_trackers": len(face_app.PERSON_TRACKER)
    })


# =========================================================
# HEALTH CHECK
# =========================================================
@app.route("/health")
def health():
    return jsonify({"status": "running"})


# =========================================================
# RUN SERVER
# =========================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Station inference HTTP server")
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()

    # 🔥 START INFERENCE ONLY HERE
    start_inference()

    app.run(
        host="0.0.0.0",
        port=args.port,
        threaded=True,
        debug=False,
        use_reloader=False
    )