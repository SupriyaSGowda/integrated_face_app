#!/usr/bin/env python3

"""Simple API gateway for managing endpoint servers.

The gateway can start/stop the three backend servers (station, detect, control)
as subprocesses and enforces a lock on model networks to prevent loading the
same model concurrently.

Usage:
    python3 gateway.py

Endpoints:
    POST /start/<name>   # name is one of station, detect, control
    POST /stop/<name>
    GET  /status         # list running state and ports
    GET  /health         # gateway health

Internally it uses ``requests`` when verifying that a backend has started.
"""

import os
import subprocess
import threading
import time

import requests
from flask import Flask, jsonify, abort, request

# import the logic modules so we can read their NETWORK_NAME constants
import logic.face_app as face_app  # station server logic
import logic.detect as detect      # 4_ppl server logic
import logic.track_room as track_room  # control room logic

app = Flask(__name__)

def _script_path(rel: str) -> str:
    return os.path.join(os.path.dirname(__file__), rel)

SERVERS = {
    "station": {
        "script": _script_path("endpoints/station_in_order_server.py"),
        "port": 5001,
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

processes: dict[str, subprocess.Popen] = {}


def is_running(name: str) -> bool:
    p = processes.get(name)
    return p is not None and p.poll() is None


def start_server(name: str):
    if name not in SERVERS:
        abort(404, f"unknown server '{name}'")

    # check for network conflicts with any running server
    requested_nets = set(SERVERS[name]["networks"])
    for other, proc in processes.items():
        if proc and proc.poll() is None:
            other_nets = set(SERVERS[other]["networks"])
            if requested_nets & other_nets:
                abort(409, f"network conflict with running '{other}'")

    if is_running(name):
        return jsonify(status="already running")

    info = SERVERS[name]
    cmd = ["python3", info["script"], "--port", str(info["port"])]
    proc = subprocess.Popen(cmd)
    processes[name] = proc
    # don't block waiting for health, caller can poll /status or /health
    return jsonify(status="started", port=info["port"])


@app.route("/start/<name>", methods=["POST"])
def start(name: str):
    return start_server(name)


@app.route("/stop/<name>", methods=["POST"])
def stop(name: str):
    if name not in SERVERS:
        abort(404)
    proc = processes.get(name)
    if proc and proc.poll() is None:
        proc.terminate()
        return jsonify(status="stopping")
    return jsonify(status="not running")


@app.route("/status", methods=["GET"])
def status():
    result = {}
    for name, info in SERVERS.items():
        result[name] = {
            "running": is_running(name),
            "port": info["port"],
            "networks": info["networks"],
        }
    return jsonify(result)


@app.route("/ping/<name>", methods=["GET"])
def ping(name: str):
    """Attempt to call the backend's health endpoint and return its response.

    This is useful when you want the gateway itself to verify that a
    subprocess is not only running but also listening and healthy.
    """
    if name not in SERVERS:
        abort(404, f"unknown server '{name}'")

    info = SERVERS[name]
    url = f"http://localhost:{info['port']}/health"
    try:
        r = requests.get(url, timeout=2)
        result = {
            "name": name,
            "port": info['port'],
            "reachable": True,
            "http_status": r.status_code,
        }
        # try to include any JSON body if possible
        try:
            result["body"] = r.json()
        except Exception:
            result["body"] = r.text
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "name": name,
            "port": info['port'],
            "reachable": False,
            "error": str(e)
        }), 502


# --------------------
# generic proxy
# --------------------
@app.route("/<name>/<path:subpath>", methods=["GET","POST","PUT","DELETE","PATCH"])
def proxy(name: str, subpath: str):
    """Forward the incoming request to the named backend.

    This allows clients to interact with the downstream endpoints via the
    gateway transparently.  Any method, headers+body, and query parameters are
    sent through; the response status, headers and body are relayed back.
    """
    if name not in SERVERS:
        abort(404, f"unknown server '{name}'")

    port = SERVERS[name]["port"]
    url = f"http://localhost:{port}/{subpath}"

    # prepare headers (exclude host to avoid confusion)
    headers = {k: v for k, v in request.headers if k.lower() != "host"}

    try:
        resp = requests.request(
            method=request.method,
            url=url,
            params=request.args,
            headers=headers,
            data=request.get_data(),
            timeout=5
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    # build a Flask response from the proxied response
    excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
    response_headers = [(name, value) for name, value in resp.raw.headers.items()
                        if name.lower() not in excluded_headers]

    return (resp.content, resp.status_code, response_headers)


@app.route("/health", methods=["GET"])
def health():
    return jsonify(status="gateway ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
