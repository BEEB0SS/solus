"""MuJoCo simulator control and sim-vs-real comparison."""

import json
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import _uid, _now

from ..database import get_connection
from ..state import simulator, live_benches

router = APIRouter()


class SimRunRequest(BaseModel):
    n_steps: int = 500
    dt: float = 0.002
    kp: float = 2.0
    target_dist: float = 0.25
    wheel_radius: float | None = None
    chassis_length: float | None = None
    chassis_width: float | None = None
    motor_torque: float | None = None


@router.post("/api/projects/{project_id}/simulator/run")
async def run_simulation(project_id: str, body: SimRunRequest):
    if not simulator:
        raise HTTPException(503, "Simulator unavailable")
    extra = {}
    if body.wheel_radius is not None:
        extra["wheel_radius"] = body.wheel_radius
    if body.chassis_length is not None:
        extra["chassis_length"] = body.chassis_length
    if body.chassis_width is not None:
        extra["chassis_width"] = body.chassis_width
    if body.motor_torque is not None:
        extra["motor_torque"] = body.motor_torque
    result = await simulator.run_simulation(
        n_steps=body.n_steps, dt=body.dt, kp=body.kp, target_dist=body.target_dist,
        **extra,
    )
    # Store run in DB
    conn = get_connection()
    run_id = _uid()
    conn.execute(
        "INSERT INTO simulation_runs (id, project_id, parameters, results, status, created_at) VALUES (?,?,?,?,?,?)",
        (run_id, project_id, json.dumps(result["params_used"]),
         json.dumps({"trajectory_len": len(result["trajectory"]), "final_state": result["final_state"]}),
         "completed", _now()),
    )
    conn.commit()
    conn.close()
    return result


@router.post("/api/projects/{project_id}/simulator/manual")
async def sim_manual_control(project_id: str, req: dict):
    """Manual control input for simulator. Updates sim state."""
    if not simulator:
        raise HTTPException(503, "Simulator unavailable")
    command = req.get("command", "")
    motor_map = {
        "FORWARD": (1.0, 1.0),
        "REVERSE": (-1.0, -1.0),
        "LEFT": (-0.6, 0.6),
        "RIGHT": (0.6, -0.6),
        "STOP": (0.0, 0.0),
    }
    left, right = motor_map.get(command.upper(), (0.0, 0.0))
    try:
        n_steps = max(1, min(int(req.get("n_steps", 500)), 2000))
    except (TypeError, ValueError):
        n_steps = 500
    result = simulator.step_manual(left, right, n_steps=n_steps)
    return result


@router.post("/api/projects/{project_id}/simulator/reset")
async def sim_reset(project_id: str):
    if simulator:
        return simulator.reset_manual()
    return {"reset": True}


@router.post("/api/projects/{project_id}/simulator/update-from-onshape")
async def update_sim_from_onshape(project_id: str, body: dict):
    if not simulator:
        raise HTTPException(503, "Simulator unavailable")

    # If body has explicit parts/dimensions, use them directly
    if body.get("parts"):
        simulator.update_from_onshape(body)
        return {"updated": True, "params": simulator.params}

    # Otherwise, fetch from the project's Onshape source
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM source_connections WHERE project_id=? AND source_type='onshape'",
        (project_id,),
    ).fetchall()
    conn.close()

    if not rows:
        raise HTTPException(404, "No Onshape source configured for this project")

    source = dict(rows[0])
    config = json.loads(source.get("config", "{}"))
    doc_id = config.get("document_id") or config.get("url", "")

    from ..connectors.onshape import OnshapeConnector
    connector = OnshapeConnector(
        doc_id,
        config.get("workspace_id", ""),
        project_id,
        os.environ.get("ONSHAPE_ACCESS_KEY", ""),
        os.environ.get("ONSHAPE_SECRET_KEY", ""),
    )

    # Use sync() which fetches mass properties + bounding boxes
    sync_result = connector.sync()
    entities = sync_result.get("entities", [])

    old_params = dict(simulator.params)

    # Extract real dimensions from entity metadata (dimensions_mm from bounding boxes)
    onshape_body = {"parts": []}
    for ent in entities:
        name = ent.name if hasattr(ent, "name") else ent.get("name", "")
        meta = ent.metadata if hasattr(ent, "metadata") else ent.get("metadata", {})
        dims_mm = meta.get("dimensions_mm", {})
        name_lower = name.lower()

        entry = {"name": name, "dimensions": {}}
        if "wheel" in name_lower and dims_mm:
            # Wheel: diameter = max bounding box dimension (mm -> m)
            vals = [dims_mm.get("x", 0), dims_mm.get("y", 0), dims_mm.get("z", 0)]
            diameter_mm = max(vals) if vals else 0
            # Width = smallest dimension
            width_mm = min(v for v in vals if v > 0) if any(v > 0 for v in vals) else 0
            if diameter_mm > 0:
                entry["dimensions"]["diameter"] = diameter_mm / 1000
            if width_mm > 0:
                entry["dimensions"]["width"] = width_mm / 1000
        elif any(k in name_lower for k in ("chassis", "body", "frame", "bottom plate")) and dims_mm:
            # Chassis: length = largest, width = middle, height = smallest
            vals = sorted([dims_mm.get("x", 0), dims_mm.get("y", 0), dims_mm.get("z", 0)], reverse=True)
            if vals[0] > 0:
                entry["dimensions"]["length"] = vals[0] / 1000
            if vals[1] > 0:
                entry["dimensions"]["width"] = vals[1] / 1000
            if vals[2] > 0:
                entry["dimensions"]["height"] = vals[2] / 1000

        if entry["dimensions"]:
            onshape_body["parts"].append(entry)

    # Try to download STL for key parts
    stl_parts = []
    raw_parts = connector.get_parts()
    for part in raw_parts:
        name_lower = part.get("name", "").lower()
        if any(k in name_lower for k in ("chassis", "wheel", "body", "frame")):
            eid = part.get("elementId", "")
            pid = part.get("partId", "")
            if eid and pid and connector.ak and connector.sk:
                stl_url = f"/parts/d/{connector.did}/w/{connector.wid}/e/{eid}/partid/{pid}/stl"
                try:
                    import requests
                    resp = requests.get(
                        f"https://cad.onshape.com/api/v6{stl_url}",
                        auth=(connector.ak, connector.sk),
                        headers={"Accept": "application/octet-stream"},
                        timeout=30,
                    )
                    if resp.status_code == 200 and len(resp.content) > 100:
                        stl_path = simulator.load_from_onshape_stl(resp.content, part["name"])
                        stl_parts.append({"name": part["name"], "stl_path": stl_path})
                except Exception as e:
                    print(f"[routes] STL download failed for {part['name']}: {e}")

    if onshape_body["parts"]:
        simulator.update_from_onshape(onshape_body)
    else:
        print("[routes] No parts with dimensions found — sim params unchanged")

    # Build change list
    changes = []
    for key in simulator.params:
        if old_params.get(key) != simulator.params[key]:
            changes.append(f"{key}: {old_params.get(key)} -> {simulator.params[key]}")

    return {
        "updated": bool(changes),
        "updated_params": simulator.params,
        "changes": changes,
        "parts_found": len(entities),
        "parts_with_dims": len(onshape_body["parts"]),
        "stl_loaded": [s["name"] for s in stl_parts],
    }


@router.get("/api/projects/{project_id}/simulator/state")
async def get_sim_state(project_id: str):
    if not simulator:
        return {"available": False}
    state = simulator.get_state()
    state["available"] = True
    state["params"] = simulator.params
    state["pid_running"] = simulator.pid_running
    return state


@router.post("/api/projects/{project_id}/simulator/step")
async def sim_pid_step(project_id: str):
    """Single PID step — returns full body state for Three.js."""
    if not simulator:
        raise HTTPException(503, "Simulator unavailable")
    state = simulator.run_pid_step()
    return state


@router.post("/api/projects/{project_id}/simulator/start-pid")
async def sim_start_pid(project_id: str, req: dict = None):
    """Mark PID as running. Frontend polls /step to advance."""
    if not simulator:
        raise HTTPException(503, "Simulator unavailable")
    params = req or {}
    if "kp" in params:
        simulator.params["kp"] = float(params["kp"])
    if "kd" in params:
        simulator.params["kd"] = float(params["kd"])
    if "target_distance" in params:
        simulator.params["target_distance"] = float(params["target_distance"])
    simulator.start_pid()
    return {"pid_running": True, "params": simulator.params}


@router.post("/api/projects/{project_id}/simulator/stop-pid")
async def sim_stop_pid(project_id: str):
    if not simulator:
        raise HTTPException(503, "Simulator unavailable")
    simulator.stop_pid()
    return {"pid_running": False}


@router.post("/api/projects/{project_id}/simulator/compare")
async def compare_sim_telemetry(project_id: str):
    if not simulator:
        raise HTTPException(503, "Simulator unavailable")
    bench = live_benches.get(project_id)
    if not bench:
        raise HTTPException(404, "Live bench not running")
    sim_result = await simulator.run_simulation()
    live_state = bench.get_current_state()
    comparisons = simulator.compare_with_telemetry(sim_result, live_state)
    return {"comparisons": comparisons, "sim_final": sim_result.get("final_state")}
