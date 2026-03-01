#!/usr/bin/env python3

import os
import subprocess
import time
import signal
import requests
from flask import Flask, jsonify, abort, request, Response, send_from_directory

# import logic modules only to read NETWORK_NAME constants
import logic.face_app as face_app
import logic.detect as detect
import logic.track_room as track_room

app = Flask(__name__)

# allow cross‑origin requests (useful if you ever bypass the dev proxy)
try:
    from flask_cors import CORS
    CORS(app)
except ImportError:
    pass


# ==========================================================
# CONFIG
# ==========================================================
def _script_path(rel: str) -> str:
    return os.path.join(os.path.dirname(__file__), rel)


SERVERS = {
    "station": {
        "script": _script_path("endpoints/station_in_order_server.py"),
        "port": 5004,
        "networks": [face_app.NETWORK_NAME],
    },
    "detect": {
        "script": _script_path("endpoints/4_ppl_server.py"),
        "port": 5002,
        "networks": [detect.NETWORK_NAME],
    },
    "control": {
        "script": _script_path("endpoints/control_room.py"),
        "port": 5003,
        "networks": [track_room.NETWORK_NAME],
    },
}

processes = {}


# ==========================================================
# UTILITIES
# ==========================================================
def is_running(name: str) -> bool:
    p = processes.get(name)
    return p is not None and p.poll() is None


def kill_process_tree(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        pass


# ==========================================================
# START SERVER
# ==========================================================
def start_server(name: str):

    if name not in SERVERS:
        abort(404, f"unknown server '{name}'")

    if is_running(name):
        return jsonify(status="already running")

    # Check network conflicts
    requested_nets = set(SERVERS[name]["networks"])

    for other, proc in processes.items():
        if proc and proc.poll() is None:
            other_nets = set(SERVERS[other]["networks"])
            if requested_nets & other_nets:
                abort(409, f"network conflict with running '{other}'")

    info = SERVERS[name]

    cmd = [
        "python3",
        info["script"],
        "--port",
        str(info["port"])
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=os.path.dirname(info["script"]),
            preexec_fn=os.setsid   # allows killing whole process group
        )
    except Exception as e:
        return jsonify(status="failed", error=str(e)), 500

    processes[name] = proc

    # Wait briefly to ensure it didn't crash immediately
    time.sleep(3)

    if proc.poll() is not None:
        return jsonify(
            status="failed",
            message="process exited immediately (check logs)"
        ), 500

    return jsonify(status="started", port=info["port"])


@app.route("/start/<name>", methods=["POST"])
def start(name):
    return start_server(name)


# ==========================================================
# STOP SERVER
# ==========================================================
@app.route("/stop/<name>", methods=["POST"])
def stop(name):

    if name not in SERVERS:
        abort(404)

    proc = processes.get(name)

    if not proc or proc.poll() is not None:
        return jsonify(status="not running")

    kill_process_tree(proc)

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        kill_process_tree(proc)

    return jsonify(status="stopped")


# ==========================================================
# STATUS
# ==========================================================
@app.route("/status", methods=["GET"])
def status():

    result = {}

    for name, info in SERVERS.items():
        running = is_running(name)

        result[name] = {
            "running": running,
            "port": info["port"],
            "networks": info["networks"]
        }

    return jsonify(result)


# ==========================================================
# HEALTH
# ==========================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="gateway ok")


# ==========================================================
# PING BACKEND
# ==========================================================
@app.route("/ping/<name>", methods=["GET"])
def ping(name):

    if name not in SERVERS:
        abort(404)

    info = SERVERS[name]
    url = f"http://localhost:{info['port']}/health"

    try:
        r = requests.get(url, timeout=2)
        return jsonify(
            name=name,
            reachable=True,
            status=r.status_code
        )
    except Exception as e:
        return jsonify(
            name=name,
            reachable=False,
            error=str(e)
        ), 502


# ==========================================================
# STREAMING PROXY (FIXED)
# ==========================================================
@app.route("/<name>/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def proxy(name, subpath):

    if name not in SERVERS:
        abort(404, f"unknown server '{name}'")

    port = SERVERS[name]["port"]
    url = f"http://localhost:{port}/{subpath}"

    headers = {k: v for k, v in request.headers if k.lower() != "host"}

    try:
        resp = requests.request(
            method=request.method,
            url=url,
            params=request.args,
            headers=headers,
            data=request.get_data(),
            stream=True,       # 🔥 IMPORTANT
            timeout=None       # 🔥 no timeout for streams
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]

    response_headers = [
        (h, v)
        for h, v in resp.raw.headers.items()
        if h.lower() not in excluded_headers
    ]

    def generate():
        try:
            for chunk in resp.iter_content(chunk_size=4096):
                if chunk:
                    yield chunk
        except Exception:
            pass

    return Response(
        generate(),
        status=resp.status_code,
        headers=response_headers
    )


# ==========================================================
# STATIC FILES (SERVE REACT BUILD IF PRESENT)
# ==========================================================
# When a React frontend is built into frontend/build, we can serve the
# compiled files directly from the gateway. Requests that don't match
# any API endpoint are forwarded to the index.html so the client-side
# router can take over.

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    build_dir = os.path.join(os.path.dirname(__file__), 'frontend', 'build')
    if path and os.path.exists(os.path.join(build_dir, path)):
        return send_from_directory(build_dir, path)
    else:
        # fallback to index.html
        return send_from_directory(build_dir, 'index.html')

# ==========================================================
# CLEAN SHUTDOWN (WHEN GATEWAY STOPS)
# ==========================================================
def shutdown_all():
    print("🛑 Gateway shutting down...")
    for proc in processes.values():
        if proc and proc.poll() is None:
            kill_process_tree(proc)


import atexit
atexit.register(shutdown_all)


# ==========================================================
# RUN
# ==========================================================
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8000,
        threaded=True,
        debug=False
    )