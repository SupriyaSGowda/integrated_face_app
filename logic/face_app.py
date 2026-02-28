#!/usr/bin/env python

import cv2
import time
import threading
import numpy as np
from collections import defaultdict
from axelera.app.stream import create_inference_stream

# simple file lock so only one process can load a given network at once
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
    "rtsp://test1:cctv8687@192.168.1.64:554/Streaming/Channels/102?transportmode=unicast&profile=Profile_1",
    "rtsp://admin:Admin123@192.168.1.106:554/ch0_0.264",
    "rtsp://admin:Admin123@192.168.1.2:554/ch0_0.264"
]

NETWORK_NAME = "wider_face_recog"
CONFIDENCE_THRESHOLD = 0.35

FRAME_WIDTH = 640
FRAME_HEIGHT = 360
JPEG_QUALITY = 45
MAX_OUTPUT_FPS = 20

EXPECTED_SEQUENCE = [0, 1, 2]
SEQUENCE_TIMEOUT = 180  # 3 minutes
CAMERA_STALE_LIMIT = 2

# =========================
# STATE
# =========================
PERSON_TRACKER = {}      # { name: {start_time, cameras_seen} }
PASSED_PERSONS = set()   # Persons who completed
LAST_ALERTS = []
LAST_COMBINED_FRAME = None
LAST_OUTPUT_TIME = 0

latest_frames = {}
camera_last_seen = defaultdict(lambda: 0)

_FRAME_LOCK = threading.Lock()
_ALERT_LOCK = threading.Lock()


def normalize_name(name: str) -> str:
    return name.split("_")[0] if "_" in name else name


def raise_alert(name, cam_id, status):
    with _ALERT_LOCK:
        LAST_ALERTS.append({
            "name": name,
            "camera_id": cam_id,
            "status": status,
            "timestamp": time.time()
        })


# =========================
# SEQUENCE LOGIC
# =========================
def handle_sequence(predicted, source_id, current_time):

    # Ignore if already passed
    if predicted in PASSED_PERSONS:
        return

    # FIRST EVER DETECTION
    if predicted not in PERSON_TRACKER:

        if source_id != 0:
            raise_alert(predicted, source_id, "ALERT_WRONG_START")
            return

        PERSON_TRACKER[predicted] = {
            "start_time": current_time,
            "cameras_seen": {0}
        }
        return

    person = PERSON_TRACKER[predicted]
    elapsed = current_time - person["start_time"]

    # TIMEOUT CHECK
    if elapsed > SEQUENCE_TIMEOUT:
        if person["cameras_seen"] != {0, 1, 2}:
            raise_alert(predicted, source_id, "ALERT_TIMEOUT")
        del PERSON_TRACKER[predicted]
        return

    # Ignore repeated detection in same camera
    if source_id in person["cameras_seen"]:
        return

    # STRICT ORDER CHECK
    if source_id == 1:
        if 0 in person["cameras_seen"]:
            person["cameras_seen"].add(1)
        else:
            raise_alert(predicted, source_id, "ALERT_WRONG_ORDER")
            del PERSON_TRACKER[predicted]
            return

    elif source_id == 2:
        if 1 in person["cameras_seen"]:
            person["cameras_seen"].add(2)
        else:
            raise_alert(predicted, source_id, "ALERT_WRONG_ORDER")
            del PERSON_TRACKER[predicted]
            return

    # CHECK COMPLETION
    if person["cameras_seen"] == {0, 1, 2}:
        raise_alert(predicted, source_id, "PASSED")
        PASSED_PERSONS.add(predicted)
        del PERSON_TRACKER[predicted]


# =========================
# MAIN LOOP
# =========================
def background_inference_loop():
    global LAST_COMBINED_FRAME, LAST_OUTPUT_TIME

    # ensure only one instance of this network is running in the system
    _acquire_model_lock()

    print("🔥 Final Corridor Logic Running")

    while True:
        try:
            stream = create_inference_stream(
                network=NETWORK_NAME,
                sources=RTSP_URLS,
                rtsp_latency=0
            )

            for frame_result in stream:

                if frame_result.meta.get("is_stale", False):
                    continue

                current_time = time.time()

                try:
                    source_id = frame_result.stream_id
                except:
                    source_id = 0

                camera_last_seen[source_id] = current_time

                rgb = frame_result.image.asarray()
                orig_h, orig_w = rgb.shape[:2]

                frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))

                scale_x = FRAME_WIDTH / orig_w
                scale_y = FRAME_HEIGHT / orig_h

                meta = frame_result.meta

                # CLEAN TIMEOUTS
                expired = []
                for name, person in PERSON_TRACKER.items():
                    if current_time - person["start_time"] > SEQUENCE_TIMEOUT:
                        expired.append(name)

                for name in expired:
                    raise_alert(name, -1, "ALERT_TIMEOUT")
                    del PERSON_TRACKER[name]

                # DETECTIONS
                if "detections" in meta:
                    detections_meta = meta["detections"]

                    for det_idx in range(len(detections_meta.boxes)):

                        x1o, y1o, x2o, y2o = map(int, detections_meta.boxes[det_idx])
                        display_name = "Face"

                        if (
                            "recognitions" in detections_meta.secondary_frame_indices
                            and det_idx in detections_meta.secondary_frame_indices["recognitions"]
                        ):
                            try:
                                recog_meta = detections_meta.get_secondary_meta(
                                    "recognitions", det_idx
                                )

                                class_ids, scores = recog_meta.get_result(0)

                                if recog_meta.labels and len(class_ids) > 0:
                                    score = float(scores[0])

                                    if score >= CONFIDENCE_THRESHOLD:
                                        predicted = normalize_name(
                                            recog_meta.labels[class_ids[0]]
                                        )

                                        display_name = f"{predicted} {score:.2f}"
                                        handle_sequence(predicted, source_id, current_time)

                            except:
                                pass

                        x1 = int(x1o * scale_x)
                        y1 = int(y1o * scale_y)
                        x2 = int(x2o * scale_x)
                        y2 = int(y2o * scale_y)

                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, display_name,
                                    (x1, max(20, y1 - 5)),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.6, (255, 255, 255), 2)

                latest_frames[source_id] = frame

                # OUTPUT FPS CONTROL
                if current_time - LAST_OUTPUT_TIME >= 1.0 / MAX_OUTPUT_FPS:
                    LAST_OUTPUT_TIME = current_time

                    combined_frames = []

                    for i in range(len(RTSP_URLS)):
                        if (
                            i in latest_frames
                            and current_time - camera_last_seen[i] < CAMERA_STALE_LIMIT
                        ):
                            combined_frames.append(latest_frames[i])
                        else:
                            black = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
                            cv2.putText(
                                black,
                                f"Camera {i} Offline",
                                (50, FRAME_HEIGHT // 2),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.8,
                                (0, 0, 255),
                                2
                            )
                            combined_frames.append(black)

                    combined = cv2.hconcat(combined_frames)

                    ok, jpeg = cv2.imencode(
                        ".jpg",
                        combined,
                        [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
                    )

                    if ok:
                        with _FRAME_LOCK:
                            LAST_COMBINED_FRAME = jpeg.tobytes()

        except Exception as e:
            print("⚠ Stream crashed, reconnecting in 2s:", e)
            time.sleep(2)


# =========================
# GETTERS
# =========================
def get_last_frame_jpeg():
    with _FRAME_LOCK:
        return LAST_COMBINED_FRAME


def get_alerts():
    with _ALERT_LOCK:
        return LAST_ALERTS.copy()