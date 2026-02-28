#!/usr/bin/env python

import cv2
import time
from datetime import datetime
from axelera.app.stream import create_inference_stream

# network locking to avoid collisions when two processes try to load the
# same network name at once
import fcntl

_model_lock_fd = None

def _acquire_model_lock():
    global _model_lock_fd
    if _model_lock_fd is not None:
        return
    lock_path = f"/tmp/model_{NETWORK_NAME}.lock"
    _model_lock_fd = open(lock_path, "w")
    try:
        fcntl.flock(_model_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        raise RuntimeError(f"network '{NETWORK_NAME}' already in use by another process")

# =========================
# CONFIG
# =========================
RTSP_URLS = [
    "rtsp://admin:cctv8686@192.168.1.64:554/ch0_0.264",
    "rtsp://admin:Admin123@192.168.1.2:554/ch0_0.264"
]

NETWORK_NAME = "wider_face_recog"
CONFIDENCE_THRESHOLD = 0.0
RTSP_LATENCY = 120
DISPLAY_HEIGHT = 480

# =========================
# GLOBAL STATE (FOR FLASK)
# =========================
present_people = set()

entry_times = {}
exit_times = {}

last_entry_detection = None
last_exit_detection = None

latest_frame = None                # EXISTING (combined)
latest_frame_entry = None          # NEW
latest_frame_exit = None           # NEW
activity_log = []

# =========================
def normalize_name(name: str) -> str:
    if not name:
        return name
    return name.split("_")[0].strip()


# =========================
def track_room():
    global latest_frame_entry, latest_frame_exit
    global last_entry_detection, last_exit_detection
    global activity_log

    # ensure only one process is tracking with this model at a time
    _acquire_model_lock()

    print("🚀 Tracking Started")

    # Keep retrying stream until successful
    while True:
        try:
            stream = create_inference_stream(
                network=NETWORK_NAME,
                sources=RTSP_URLS,
                rtsp_latency=RTSP_LATENCY
            )
            break
        except Exception as e:
            print("Stream failed. Retrying...", e)
            time.sleep(2)

    # Loop over frames
    for frame_result in stream:

        if frame_result.meta.get("is_stale", False):
            continue

        source_id = getattr(frame_result, "stream_id", 0)

        rgb = frame_result.image.asarray()
        frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        meta = frame_result.meta

        # =========================
        # FACE DETECTION / RECOGNITION
        # =========================
        if "detections" in meta:

            detections_meta = meta["detections"]

            for det_idx in range(len(detections_meta.boxes)):

                name = None

                if ('recognitions' in detections_meta.secondary_frame_indices and
                        det_idx in detections_meta.secondary_frame_indices['recognitions']):

                    try:
                        recog_meta = detections_meta.get_secondary_meta(
                            'recognitions', det_idx
                        )

                        class_ids, scores = recog_meta.get_result(0)

                        if recog_meta.labels and len(class_ids) > 0:

                            predicted_name = recog_meta.labels[class_ids[0]]
                            predicted_score = float(scores[0])

                            if predicted_score >= CONFIDENCE_THRESHOLD:
                                name = normalize_name(predicted_name)

                    except:
                        pass

                if not name:
                    continue

                now = datetime.now().strftime("%H:%M:%S")

                # =========================
                # ENTRY CAMERA (RTSP 1)
                # =========================
                if source_id == 0:
                    if name not in present_people:
                        present_people.add(name)
                        entry_times[name] = now
                        # if they had a previous exit time, clear it on re-entry
                        if name in exit_times:
                            del exit_times[name]

                        last_entry_detection = {
                            "name": name,
                            "time": now
                        }

                        activity_log.insert(0, {
                            "id": f"{name}-{now}-{len(activity_log)}",
                            "timestamp": now,
                            "person": name,
                            "action": "ENTERED"
                        })

                        print(f"🟢 ENTRY: {name}")

                # =========================
                # EXIT CAMERA (RTSP 2)
                # =========================
                elif source_id == 1:
                    if name in present_people:
                        present_people.remove(name)
                        exit_times[name] = now

                        last_exit_detection = {
                            "name": name,
                            "time": now
                        }

                        activity_log.insert(0, {
                            "id": f"{name}-{now}-{len(activity_log)}",
                            "timestamp": now,
                            "person": name,
                            "action": "EXITED"
                        })

                        print(f"🔴 EXIT: {name}")

                # Prevent memory explosion
                if len(activity_log) > 100:
                    activity_log.pop()

        # =========================
        # STORE FRAMES INDEPENDENTLY
        # =========================
        if source_id == 0:
            latest_frame_entry = frame.copy()

        elif source_id == 1:
            latest_frame_exit = frame.copy()