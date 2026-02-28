#!/usr/bin/env python3

# bring workspace root onto sys.path so the logic package can be imported
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, Response, jsonify
import threading
import time
from logic import face_app
import atexit

app = Flask(__name__)

# =========================================
# START BACKGROUND INFERENCE (SAFE START)
# =========================================
inference_thread_started = False
inference_lock = threading.Lock()
inference_thread = None


def ensure_inference_running():
    global inference_thread_started, inference_thread

    with inference_lock:
        if not inference_thread_started:
            inference_thread = threading.Thread(
                target=face_app.background_inference_loop,
                daemon=True
            )
            inference_thread.start()
            inference_thread_started = True
            print("🔥 Inference thread started")


# Start immediately when module loads (safe in Flask 3)
ensure_inference_running()


# =========================================
# CLEAN SHUTDOWN HANDLER
# =========================================
def cleanup():
    print("🛑 Flask shutting down...")

atexit.register(cleanup)


# =========================================
# MJPEG STREAM (OPTIMIZED)
# =========================================
def mjpeg_stream():
    last_frame = None

    while True:
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


# =========================================
# VIDEO FEED
# =========================================
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


# =========================================
# ALERT API
# =========================================
@app.route("/alerts")
def api_alerts():
    try:
        alerts = face_app.get_alerts()

        if alerts:
            if hasattr(face_app, "_ALERT_LOCK"):
                with face_app._ALERT_LOCK:
                    face_app.LAST_ALERTS.clear()

        return jsonify({
            "count": len(alerts),
            "alerts": alerts
        })

    except Exception as e:
        print("⚠ Alert API error:", e)
        return jsonify({"error": str(e)}), 500


# =========================================
# STATUS API
# =========================================
@app.route("/status")
def api_status():
    return jsonify({
        "status": "running",
        "inference_thread_alive": inference_thread.is_alive() if inference_thread else False,
        "num_cams": len(face_app.RTSP_URLS),
        "active_trackers": len(face_app.PERSON_TRACKER)
    })


# =========================================
# HEALTH CHECK
# =========================================
@app.route("/health")
def health():
    return jsonify({"status": "running"})


# =========================================
# RUN SERVER
# =========================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Station inference HTTP server")
    parser.add_argument("--port", type=int, default=5001,
                        help="port to bind the Flask app")
    args = parser.parse_args()

    app.run(
        host="0.0.0.0",
        port=args.port,
        threaded=True,
        debug=False,
        use_reloader=False
    )