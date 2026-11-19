
import os
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

import cv2
import numpy as np
from ultralytics import YOLO

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MODEL_PATH = BASE_DIR / "models" / "model.pt"

# Replace this with your phone's IP Webcam stream address.
CAMERA_URL = os.getenv(
    "SURFIRE_CAMERA_URL",
    "http://192.168.1.23:8080/video"
)

CONFIDENCE_THRESHOLD = 0.25
IMAGE_SIZE = 416
INFERENCE_INTERVAL = 0.5
DETECTION_CLASSES = {"fire", "fire-smoke"}
DETECTION_CLEAR_DELAY = 3.0

START_TIME = monotonic()

# RLock allows nested calls while shared state is locked.
lock = threading.RLock()
frame_lock = threading.Lock()

stop_event = threading.Event()

camera_thread = None
inference_thread = None

# Shared frames and annotations
latest_raw_frame = None
latest_jpeg = None
latest_detections = []

last_fire_seen = 0
fire_latched = False
last_camera_log = 0

camera_state = {
    "status": "connecting",
    "message": "Waiting for camera connection",
    "model_loaded": False
}

def timestamp():
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------
# NODE REGISTRY
# --------------------------------------------------

nodes = [
    {
        "id": "node-01",
        "name": "NODE 01",
        "sector": "Sector A",
        "location": "Prototype monitoring station",
        "status": "online",
        "camera_status": "connecting",
        "detection": "standby",
        "detection_class": None,
        "confidence": None,
        "gas_raw": None,
        "last_seen": timestamp(),
        "demo": True
    }
]

for i in range(2, 6):
    nodes.append({
        "id": f"node-{i:02d}",
        "name": f"NODE {i:02d}",
        "sector": f"Sector {chr(64 + i)}",
        "location": "Planned monitoring area",
        "status": "placeholder",
        "camera_status": "offline",
        "detection": "standby",
        "detection_class": None,
        "confidence": None,
        "gas_raw": None,
        "last_seen": None,
        "demo": False
    })


# --------------------------------------------------
# INCIDENTS AND LOGS
# --------------------------------------------------

incidents = []
logs = []


def add_log(level, message, node_id=None):
    with lock:
        logs.insert(0, {
            "time": timestamp(),
            "level": level,
            "message": message,
            "node_id": node_id
        })

        del logs[200:]


add_log("INFO", "SurFire server initialized.")
add_log("INFO", "Node registry loaded: 1 prototype, 4 placeholders.")
add_log("INFO", "Camera and YOLO monitoring initialized.")


# --------------------------------------------------
# REQUEST MODELS
# --------------------------------------------------

class Telemetry(BaseModel):
    gas_raw: int = Field(ge=0, le=4095)


class Detection(BaseModel):
    detected: bool
    detection_class: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def find_node(node_id):
    for node in nodes:
        if node["id"] == node_id:
            return node

    raise HTTPException(status_code=404, detail="Node not found")


def get_runtime():
    return int(monotonic() - START_TIME)


def get_summary():
    active_nodes = sum(
        node["status"] == "online" for node in nodes
    )

    active_incidents = sum(
        incident["status"] == "active" for incident in incidents
    )

    resolved_incidents = sum(
        incident["status"] == "resolved" for incident in incidents
    )

    return {
        "active_nodes": active_nodes,
        "active_incidents": active_incidents,
        "total_nodes": len(nodes),
        "resolved_incidents": resolved_incidents,
        "runtime": get_runtime()
    }


# --------------------------------------------------
# YOLO DETECTION PROCESSING
# --------------------------------------------------

def process_yolo_result(result):
    global last_fire_seen, fire_latched

    best_detection = None

    if result.boxes is not None:
        for box in result.boxes:
            class_id = int(box.cls[0])
            class_name = result.names[class_id]
            confidence = float(box.conf[0])

            # Only these two model classes trigger a warning.
            if class_name not in DETECTION_CLASSES:
                continue

            if confidence < CONFIDENCE_THRESHOLD:
                continue

            if (
                best_detection is None
                or confidence > best_detection["confidence"]
            ):
                best_detection = {
                    "class": class_name,
                    "confidence": confidence
                }

    current_time = monotonic()

    with lock:
        node = find_node("node-01")

        if best_detection:
            last_fire_seen = current_time

            node["detection"] = "warning"
            node["detection_class"] = best_detection["class"]
            node["confidence"] = best_detection["confidence"]
            node["last_seen"] = timestamp()
            node["demo"] = False

            if not fire_latched:
                fire_latched = True

                existing = next(
                    (
                        item for item in incidents
                        if item["node_id"] == "node-01"
                        and item["status"] == "active"
                    ),
                    None
                )

                if existing is None:
                    incident_id = max(
                        (item["id"] for item in incidents),
                        default=0
                    ) + 1

                    incidents.insert(0, {
                        "id": incident_id,
                        "node_id": "node-01",
                        "node_name": node["name"],
                        "sector": node["sector"],
                        "time": timestamp(),
                        "detection_class": best_detection["class"],
                        "confidence": best_detection["confidence"],
                        "gas_raw": node["gas_raw"],
                        "status": "active",
                        "resolved_time": None,
                        "demo": False
                    })

                    add_log(
                        "WARNING",
                        f"Potential fire detected: "
                        f"{best_detection['class']} "
                        f"({best_detection['confidence']:.1%})",
                        "node-01"
                    )

        elif (
            fire_latched
            and current_time - last_fire_seen > DETECTION_CLEAR_DELAY
        ):
            fire_latched = False

            node["detection"] = "standby"
            node["detection_class"] = None
            node["confidence"] = None

            add_log(
                "INFO",
                "No further qualifying detections. Node returned to standby.",
                "node-01"
            )


# --------------------------------------------------
# CAMERA AND YOLO BACKGROUND WORKER
# --------------------------------------------------


def inference_worker():
    global latest_raw_frame, latest_detections

    model = None

    # Load YOLO independently of the camera capture thread.
    try:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"YOLO model not found: {MODEL_PATH}")

        model = YOLO(str(MODEL_PATH))

        with lock:
            camera_state["model_loaded"] = True

        add_log("INFO", "YOLO model loaded successfully.")

        print("SurFire: YOLO model loaded.")
        print("Model classes:", model.names)

    except Exception as error:
        print("YOLO model loading failed:", error)
        add_log("ERROR", f"YOLO model loading failed: {error}")

        with lock:
            camera_state["model_loaded"] = False

        return

    # Run inference periodically using the newest available frame.
    while not stop_event.is_set():

        if stop_event.wait(INFERENCE_INTERVAL):
            break

        with frame_lock:
            if latest_raw_frame is None:
                continue

            frame = latest_raw_frame.copy()

        try:
            results = model.predict(
                source=frame,
                imgsz=IMAGE_SIZE,
                conf=CONFIDENCE_THRESHOLD,
                verbose=False
            )

            result = results[0]
            detections = []

            if result.boxes is not None:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    class_name = result.names[class_id]
                    confidence = float(box.conf[0])

                    if class_name not in DETECTION_CLASSES:
                        continue

                    if confidence < CONFIDENCE_THRESHOLD:
                        continue

                    x1, y1, x2, y2 = map(
                        int,
                        box.xyxy[0].tolist()
                    )

                    detections.append({
                        "box": (x1, y1, x2, y2),
                        "class": class_name,
                        "confidence": confidence
                    })

            # Publish annotations for the camera thread.
            with frame_lock:
                latest_detections = detections

            process_yolo_result(result)

        except Exception as error:
            print("YOLO inference error:", error)

    print("SurFire: Inference worker stopped.")


def camera_worker():
    global latest_raw_frame, latest_jpeg
    global latest_detections, last_camera_log

    while not stop_event.is_set():
        cap = None

        try:
            print("SurFire: Connecting to IP Webcam...")

            cap = cv2.VideoCapture(
                CAMERA_URL,
                cv2.CAP_FFMPEG
            )

            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            if not cap.isOpened():
                raise RuntimeError("Could not open IP Webcam stream")

            with lock:
                camera_state["status"] = "online"
                camera_state["message"] = "Camera connected"
                find_node("node-01")["camera_status"] = "online"

            add_log(
                "INFO",
                "IP Webcam connected successfully.",
                "node-01"
            )

            print("SurFire: Camera connected.")

            while not stop_event.is_set():
                success, frame = cap.read()

                if not success:
                    raise RuntimeError("Camera stream disconnected")

                # Publish the newest raw frame for YOLO.
                with frame_lock:
                    latest_raw_frame = frame.copy()
                    detections = list(latest_detections)

                # Draw the latest available YOLO annotations.
                for detection in detections:
                    x1, y1, x2, y2 = detection["box"]

                    label = (
                        f'{detection["class"]} '
                        f'{detection["confidence"]:.1%}'
                    )

                    cv2.rectangle(
                        frame,
                        (x1, y1),
                        (x2, y2),
                        (0, 220, 80),
                        2
                    )

                    cv2.putText(
                        frame,
                        label,
                        (x1, max(y1 - 10, 20)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 220, 80),
                        2
                    )

                # Encode and publish the newest annotated frame.
                success, encoded = cv2.imencode(
                    ".jpg",
                    frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 75]
                )

                if success:
                    with frame_lock:
                        latest_jpeg = encoded.tobytes()

                with lock:
                    find_node("node-01")["last_seen"] = timestamp()

        except Exception as error:
            with lock:
                camera_state["status"] = "offline"
                camera_state["message"] = str(error)
                find_node("node-01")["camera_status"] = "offline"

                if monotonic() - last_camera_log > 10:
                    add_log(
                        "WARNING",
                        f"Camera unavailable: {error}",
                        "node-01"
                    )
                    last_camera_log = monotonic()

            with frame_lock:
                latest_raw_frame = None
                latest_jpeg = None
                latest_detections = []

            print("SurFire camera:", error)

        finally:
            if cap is not None:
                cap.release()

        if not stop_event.is_set():
            stop_event.wait(3)

    print("SurFire: Camera worker stopped.")


def start_monitoring():
    global camera_thread, inference_thread

    stop_event.clear()

    camera_thread = threading.Thread(
        target=camera_worker,
        daemon=True
    )

    inference_thread = threading.Thread(
        target=inference_worker,
        daemon=True
    )

    camera_thread.start()
    inference_thread.start()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    start_monitoring()

    yield

    # Shutdown
    stop_event.set()

    if camera_thread and camera_thread.is_alive():
        camera_thread.join(timeout=3)

    if inference_thread and inference_thread.is_alive():
        inference_thread.join(timeout=3)

app = FastAPI(
    title="SurFire",
    description="Forest Fire Detection and Early Warning System",
    version="0.2.0",
    lifespan=lifespan
)

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static"
)

# --------------------------------------------------
# VIDEO STREAM
# --------------------------------------------------

waiting_frame = np.zeros((360, 640, 3), dtype=np.uint8)

cv2.putText(
    waiting_frame,
    "SURFIRE - WAITING FOR CAMERA",
    (65, 180),
    cv2.FONT_HERSHEY_SIMPLEX,
    0.8,
    (150, 180, 150),
    2
)

_, waiting_jpeg = cv2.imencode(".jpg", waiting_frame)
WAITING_JPEG = waiting_jpeg.tobytes()


def generate_video():
    while True:
        with frame_lock:
            frame = latest_jpeg

        if frame is None:
            frame = WAITING_JPEG

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame
            + b"\r\n"
        )

        time.sleep(0.05)


@app.get("/video_feed")
def video_feed():
    return StreamingResponse(
        generate_video(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/api/camera/status")
def get_camera_status():
    with lock:
        return camera_state.copy()


# --------------------------------------------------
# DASHBOARD PAGE
# --------------------------------------------------

@app.get("/")
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


# --------------------------------------------------
# DASHBOARD API
# --------------------------------------------------

@app.get("/api/state")
def get_state():
    with lock:
        return {
            "summary": get_summary(),
            "nodes": nodes,
            "incidents": incidents,
            "logs": logs,
            "server_time": timestamp()
        }


@app.get("/api/health")
def health():
    return {
        "status": "online",
        "runtime": get_runtime()
    }


# --------------------------------------------------
# ESP32 TELEMETRY API
# --------------------------------------------------

@app.post("/api/nodes/{node_id}/telemetry")
def receive_telemetry(node_id: str, data: Telemetry):
    with lock:
        node = find_node(node_id)

        if node["status"] == "placeholder":
            raise HTTPException(
                status_code=400,
                detail="Cannot send telemetry to a placeholder node"
            )

        node["gas_raw"] = data.gas_raw
        node["last_seen"] = timestamp()
        node["demo"] = False

        add_log(
            "INFO",
            f"MQ-2 telemetry received: {data.gas_raw}",
            node_id
        )

        return {
            "success": True,
            "message": "Telemetry received"
        }


# --------------------------------------------------
# MANUAL DETECTION API
# --------------------------------------------------

@app.post("/api/nodes/{node_id}/detection")
def receive_detection(node_id: str, data: Detection):
    with lock:
        node = find_node(node_id)

        if node["status"] == "placeholder":
            raise HTTPException(
                status_code=400,
                detail="Placeholder node"
            )

        node["demo"] = False
        node["last_seen"] = timestamp()

        if not data.detected:
            node["detection"] = "standby"
            node["detection_class"] = None
            node["confidence"] = None

            add_log("INFO", "Detection cleared.", node_id)

            return {
                "success": True,
                "status": "standby"
            }

        node["detection"] = "warning"
        node["detection_class"] = data.detection_class
        node["confidence"] = data.confidence

        existing = next(
            (
                item for item in incidents
                if item["node_id"] == node_id
                and item["status"] == "active"
            ),
            None
        )

        if existing is None:
            incident_id = max(
                (item["id"] for item in incidents),
                default=0
            ) + 1

            incidents.insert(0, {
                "id": incident_id,
                "node_id": node_id,
                "node_name": node["name"],
                "sector": node["sector"],
                "time": timestamp(),
                "detection_class": data.detection_class,
                "confidence": data.confidence,
                "gas_raw": node["gas_raw"],
                "status": "active",
                "resolved_time": None,
                "demo": False
            })

            add_log(
                "WARNING",
                f"Potential fire detected: {data.detection_class}",
                node_id
            )

        return {
            "success": True,
            "status": "warning"
        }


# --------------------------------------------------
# INCIDENT RESOLUTION API
# --------------------------------------------------

@app.post("/api/incidents/{incident_id}/resolve")
def resolve_incident(incident_id: int):
    with lock:
        incident = next(
            (item for item in incidents if item["id"] == incident_id),
            None
        )

        if incident is None:
            raise HTTPException(
                status_code=404,
                detail="Incident not found"
            )

        if incident["status"] == "resolved":
            return {
                "success": True,
                "message": "Already resolved"
            }

        incident["status"] = "resolved"
        incident["resolved_time"] = timestamp()

        node = find_node(incident["node_id"])
        node["detection"] = "standby"
        node["detection_class"] = None
        node["confidence"] = None

        add_log(
            "INFO",
            f"Incident #{incident_id} manually marked resolved.",
            incident["node_id"]
        )

        return {
            "success": True,
            "message": "Incident marked resolved"
        }
