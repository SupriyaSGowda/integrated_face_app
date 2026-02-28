#!/usr/bin/env python

import cv2
import time
from axelera.app.stream import create_inference_stream
#rtsp://admin:cctv8686@192.168.1.64:554/ch0_0.264

# network lock to avoid two processes loading the same models simultaneously
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

RTSP_URL = "rtsp://admin:admin@192.168.1.106:554/ch0_0.264"
NETWORK_NAME = "yolov8-face-enrollment"
CONFIDENCE_THRESHOLD = 0.0

# Shared State
person_count_global = 0
room_status_global = "UNKNOWN"
current_frame_jpeg = None
last_update_time = None

def run_room_monitor(show_window=True):

    global person_count_global
    global room_status_global
    global current_frame_jpeg
    global last_update_time

    # acquire exclusive model lock
    _acquire_model_lock()

    print("🏠 Room Monitoring Started")

    stream = create_inference_stream(
        network=NETWORK_NAME,
        sources=[RTSP_URL],
        rtsp_latency=200
    )

    try:
        for frame_result in stream:

            rgb = frame_result.image.asarray()
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

            meta = frame_result.meta
            current_time = time.time()
            person_count = 0

            # Detection
            if "detections" in meta:
                detections_meta = meta["detections"]

                for i in range(len(detections_meta.boxes)):
                    score = float(detections_meta.scores[i])
                    if score < CONFIDENCE_THRESHOLD:
                        continue

                    x1, y1, x2, y2 = map(int, detections_meta.boxes[i])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    person_count += 1

            person_count_global = person_count
            last_update_time = current_time

            # Status Logic
            if person_count == 4:
                room_status_global = "NORMAL"
            elif person_count == 2:
                room_status_global = "ON_BREAK"
            elif person_count == 1:
                room_status_global = "CRITICAL"
            else:
                room_status_global = "OTHER"

            # Encode clean frame (NO TEXT OVERLAY)
            ret, buffer = cv2.imencode(".jpg", frame)
            if ret:
                current_frame_jpeg = buffer.tobytes()

            if show_window:
                cv2.imshow("Room Monitor", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    break

    finally:
        stream.stop()
        cv2.destroyAllWindows()