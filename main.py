
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

START_TIME = monotonic()
lock = Lock()

app = FastAPI(
    title="SurFire",
    description="Forest Fire Detection and Early Warning System",
    version="0.1.0"
)

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static"
)


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
        "camera_status": "demo",
        "detection": "standby",
        "detection_class": None,
        "confidence": None,
        "gas_raw": None,
        "last_seen": timestamp(),
        "demo": True
    },
    {
        "id": "node-02",
        "name": "NODE 02",
        "sector": "Sector B",
        "location": "Planned monitoring area",
        "status": "placeholder",
        "camera_status": "offline",
        "detection": "standby",
        "detection_class": None,
        "confidence": None,
        "gas_raw": None,
        "last_seen": None,
        "demo": False
    },
    {
        "id": "node-03",
        "name": "NODE 03",
        "sector": "Sector C",
        "location": "Planned monitoring area",
        "status": "placeholder",
        "camera_status": "offline",
        "detection": "standby",
        "detection_class": None,
        "confidence": None,
        "gas_raw": None,
        "last_seen": None,
        "demo": False
    },
    {
        "id": "node-04",
        "name": "NODE 04",
        "sector": "Sector D",
        "location": "Planned monitoring area",
        "status": "placeholder",
        "camera_status": "offline",
        "detection": "standby",
        "detection_class": None,
        "confidence": None,
        "gas_raw": None,
        "last_seen": None,
        "demo": False
    },
    {
        "id": "node-05",
        "name": "NODE 05",
        "sector": "Sector E",
        "location": "Planned monitoring area",
        "status": "placeholder",
        "camera_status": "offline",
        "detection": "standby",
        "detection_class": None,
        "confidence": None,
        "gas_raw": None,
        "last_seen": None,
        "demo": False
    }
]


# --------------------------------------------------
# INCIDENTS AND LOGS
# --------------------------------------------------

incidents = []
logs = []


def add_log(level, message, node_id=None):
    logs.insert(0, {
        "time": timestamp(),
        "level": level,
        "message": message,
        "node_id": node_id
    })

    del logs[200:]


add_log("INFO", "SurFire server initialized.")
add_log("INFO", "Node registry loaded: 1 prototype, 4 placeholders.")
add_log("INFO", "Demo mode enabled. No live sensor data received.")


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

        return {"success": True, "message": "Telemetry received"}


# --------------------------------------------------
# YOLO DETECTION API
# --------------------------------------------------

@app.post("/api/nodes/{node_id}/detection")
def receive_detection(node_id: str, data: Detection):
    with lock:
        node = find_node(node_id)

        if node["status"] == "placeholder":
            raise HTTPException(status_code=400, detail="Placeholder node")

        node["demo"] = False
        node["last_seen"] = timestamp()

        if not data.detected:
            node["detection"] = "standby"
            node["detection_class"] = None
            node["confidence"] = None
            add_log("INFO", "Detection cleared.", node_id)
            return {"success": True, "status": "standby"}

        node["detection"] = "warning"
        node["detection_class"] = data.detection_class
        node["confidence"] = data.confidence

        # Avoid creating duplicate active incidents for one node.
        existing = next(
            (
                item for item in incidents
                if item["node_id"] == node_id
                and item["status"] == "active"
            ),
            None
        )

        if existing is None:
            incident = {
                "id": len(incidents) + 1,
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
            }

            incidents.insert(0, incident)

            add_log(
                "WARNING",
                f"Potential fire detected: {data.detection_class}",
                node_id
            )

        return {"success": True, "status": "warning"}


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
            raise HTTPException(status_code=404, detail="Incident not found")

        if incident["status"] == "resolved":
            return {"success": True, "message": "Already resolved"}

        incident["status"] = "resolved"
        incident["resolved_time"] = timestamp()

        node = find_node(incident["node_id"])
        node["detection"] = "standby"

        add_log(
            "INFO",
            f"Incident #{incident_id} manually marked resolved.",
            incident["node_id"]
        )

        return {
            "success": True,
            "message": "Incident marked resolved"
        }
