"""
Solus API routes — all endpoints in one file.
"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'packages', 'shared-types', 'src'))
from models import (
    Project, Entity, Relation, TeamMember, SourceConnection, ChangeEvent,
    Issue, Fix, Anomaly, AgentQuery, SimulationRun,
    EntityType, RelationType, SourceType, ChangeType, IssueStatus,
    _uid, _now,
)

from .database import get_connection

router = APIRouter()

# ── Optional imports ──────────────────────────────────────────────────

try:
    from .context_engine import ContextEngine
    context_engine = ContextEngine()
except Exception as e:
    print(f"[warn] ContextEngine unavailable: {e}")
    context_engine = None

try:
    from .agent.solus_agent import SolusAgent
    from .agent.memory_store import MemoryStore
    memory_store = MemoryStore()
    solus_agent = SolusAgent(context_engine=context_engine, memory_store=memory_store)
except Exception as e:
    print(f"[warn] Agent unavailable: {e}")
    solus_agent = None
    memory_store = None

from .live_bench import LiveBench
from .arduino_flasher import ArduinoFlasher

try:
    from .simulator import MuJoCoSimulator
    simulator = MuJoCoSimulator()
except Exception:
    simulator = None

live_benches: dict[str, LiveBench] = {}
flasher = ArduinoFlasher()

# WebSocket connections per project
ws_connections: dict[str, list[WebSocket]] = {}


# ── Helpers ───────────────────────────────────────────────────────────

def build_signal_entity_map(project_id: str) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    if not context_engine:
        return mapping
    try:
        entities = context_engine.get_entities(project_id)
        for e in entities:
            etype = e.get("entity_type", "") if isinstance(e, dict) else getattr(e, "entity_type", "")
            eid = e.get("id", "") if isinstance(e, dict) else getattr(e, "id", "")
            name = (e.get("name", "") if isinstance(e, dict) else getattr(e, "name", "")).lower()

            if "motor" in name or etype in ("electrical_part",) and "tb6612" in name.lower():
                mapping.setdefault("left_motor", []).append(eid)
                mapping.setdefault("right_motor", []).append(eid)
            if "ultrasonic" in name or "hc-sr04" in name:
                mapping.setdefault("distance_cm", []).append(eid)
            if "motor" in name and "code" in name:
                mapping.setdefault("left_motor", []).append(eid)
                mapping.setdefault("right_motor", []).append(eid)
    except Exception as e:
        print(f"[routes] build_signal_entity_map error: {e}")
    return mapping


async def broadcast_ws(project_id: str, msg: dict):
    conns = ws_connections.get(project_id, [])
    dead = []
    for ws in conns:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        conns.remove(ws)


# ── Pydantic request models ──────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    description: str = ""

class EntityCreate(BaseModel):
    entity_type: str
    name: str
    description: str = ""
    metadata: dict = {}
    source: str = "manual"
    source_ref: str = ""

class RelationCreate(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    metadata: dict = {}
    confidence: float = 1.0

class TeamMemberCreate(BaseModel):
    name: str
    role: str = ""
    email: str = ""

class SourceCreate(BaseModel):
    source_type: str
    name: str
    config: dict = {}

class AgentQueryCreate(BaseModel):
    query: str
    query_type: str = "general"
    context_entity_ids: list = []

class IssueCreate(BaseModel):
    title: str
    description: str = ""
    related_entity_ids: list = []
    reported_by: str = ""

class FixCreate(BaseModel):
    issue_id: str
    description: str = ""
    steps: list = []
    applied_by: str = ""

class LiveBenchStart(BaseModel):
    mode: str = "simulated"
    port: str = "/dev/ttyUSB0"
    baud: int = 9600

class SerialCommand(BaseModel):
    command: str

class SimRunRequest(BaseModel):
    n_steps: int = 500
    dt: float = 0.002
    kp: float = 2.0
    target_dist: float = 0.25

class SimParamUpdate(BaseModel):
    name: str
    value: float

class FlashRequest(BaseModel):
    name: str
    code: str
    port: str = ""
    fqbn: str = "arduino:avr:uno"


# ── Health ────────────────────────────────────────────────────────────

@router.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "0.2.0",
        "context_engine": context_engine is not None,
        "agent": solus_agent is not None,
        "simulator": simulator is not None,
    }


# ── Projects ──────────────────────────────────────────────────────────

@router.post("/api/projects")
async def create_project(body: ProjectCreate):
    p = Project(name=body.name, description=body.description)
    conn = get_connection()
    conn.execute(
        "INSERT INTO projects (id, name, description, created_at, updated_at) VALUES (?,?,?,?,?)",
        (p.id, p.name, p.description, p.created_at, p.updated_at),
    )
    conn.commit()
    conn.close()
    return {"id": p.id, "name": p.name, "description": p.description,
            "created_at": p.created_at, "updated_at": p.updated_at}


@router.get("/api/projects")
async def list_projects():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


# ── Team ──────────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/team")
async def add_team_member(project_id: str, body: TeamMemberCreate):
    m = TeamMember(project_id=project_id, name=body.name, role=body.role, email=body.email)
    conn = get_connection()
    conn.execute(
        "INSERT INTO team_members (id, project_id, name, role, email) VALUES (?,?,?,?,?)",
        (m.id, m.project_id, m.name, m.role, m.email),
    )
    conn.commit()
    conn.close()
    return {"id": m.id, "name": m.name, "role": m.role, "email": m.email}


@router.get("/api/projects/{project_id}/team")
async def list_team(project_id: str):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM team_members WHERE project_id=?", (project_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Sources ───────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/sources")
async def add_source(project_id: str, body: SourceCreate):
    sc = SourceConnection(
        project_id=project_id, source_type=SourceType(body.source_type),
        name=body.name, config=body.config,
    )
    conn = get_connection()
    conn.execute(
        "INSERT INTO source_connections (id, project_id, source_type, name, config, status) VALUES (?,?,?,?,?,?)",
        (sc.id, sc.project_id, sc.source_type.value, sc.name, json.dumps(sc.config), sc.status),
    )
    conn.commit()
    conn.close()
    return {"id": sc.id, "source_type": sc.source_type.value, "name": sc.name, "status": sc.status}


@router.get("/api/projects/{project_id}/sources")
async def list_sources(project_id: str):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM source_connections WHERE project_id=?", (project_id,)).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d.get("config", "{}"))
        results.append(d)
    return results


# ── Sync ──────────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/sources/{source_id}/sync")
async def sync_source(project_id: str, source_id: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM source_connections WHERE id=? AND project_id=?",
                       (source_id, project_id)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Source not found")
    source = dict(row)
    source["config"] = json.loads(source.get("config", "{}"))
    source_type = source["source_type"]
    conn.close()

    # Dispatch to connector
    connector = None
    try:
        if source_type == "github":
            from .connectors.github_connector import GitHubConnector
            connector = GitHubConnector(source["config"])
        elif source_type == "kicad":
            from .connectors.kicad_connector import KiCadConnector
            connector = KiCadConnector(source["config"])
        elif source_type == "onshape":
            from .connectors.onshape_connector import OnshapeConnector
            connector = OnshapeConnector(source["config"])
    except ImportError as e:
        raise HTTPException(500, f"Connector not available: {e}")

    if not connector:
        raise HTTPException(400, f"Unknown source type: {source_type}")

    try:
        ingested = connector.ingest()
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {e}")

    # Create entities and relations via context engine
    created_entities = []
    if context_engine:
        for ent_data in ingested.get("entities", []):
            ent = Entity(
                project_id=project_id,
                entity_type=EntityType(ent_data.get("entity_type", "software_module")),
                name=ent_data["name"],
                description=ent_data.get("description", ""),
                metadata=ent_data.get("metadata", {}),
                source=SourceType(source_type),
                source_ref=ent_data.get("source_ref", ""),
            )
            context_engine.add_entity(ent)
            created_entities.append(ent)

        for rel_data in ingested.get("relations", []):
            rel = Relation(
                project_id=project_id,
                source_entity_id=rel_data["source_entity_id"],
                target_entity_id=rel_data["target_entity_id"],
                relation_type=RelationType(rel_data.get("relation_type", "connected_to")),
            )
            context_engine.add_relation(rel)

        # Snapshot and diff
        try:
            context_engine.create_snapshot(source_id, project_id)
        except Exception:
            pass

    # Log change events
    now = _now()
    conn = get_connection()
    for ent in created_entities:
        ce = ChangeEvent(
            project_id=project_id,
            source_connection_id=source_id,
            change_type=ChangeType.ADDED,
            entity_id=ent.id,
            entity_name=ent.name,
            description=f"Synced from {source_type}",
            attributed_to=source_type,
        )
        conn.execute(
            "INSERT INTO change_events (id, project_id, source_connection_id, change_type, entity_id, entity_name, description, attributed_to, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (ce.id, ce.project_id, ce.source_connection_id, ce.change_type.value,
             ce.entity_id, ce.entity_name, ce.description, ce.attributed_to, ce.created_at),
        )

    # Update source last_synced_at
    conn.execute("UPDATE source_connections SET last_synced_at=?, status='connected' WHERE id=?",
                 (now, source_id))
    conn.commit()
    conn.close()

    # Broadcast activity
    await broadcast_ws(project_id, {
        "event": "team_activity",
        "source_type": source_type,
        "entities_created": len(created_entities),
    })

    return {
        "synced": True,
        "entities_created": len(created_entities),
        "source_type": source_type,
    }


# ── Entities ──────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/entities")
async def create_entity(project_id: str, body: EntityCreate):
    ent = Entity(
        project_id=project_id,
        entity_type=EntityType(body.entity_type),
        name=body.name,
        description=body.description,
        metadata=body.metadata,
        source=SourceType(body.source),
        source_ref=body.source_ref,
    )
    conn = get_connection()
    conn.execute(
        "INSERT INTO entities (id, project_id, entity_type, name, description, metadata, source, source_ref, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (ent.id, ent.project_id, ent.entity_type.value, ent.name, ent.description,
         json.dumps(ent.metadata), ent.source.value, ent.source_ref, ent.created_at, ent.updated_at),
    )
    conn.commit()
    conn.close()
    if context_engine:
        try:
            context_engine.add_entity(ent)
        except Exception:
            pass
    return {"id": ent.id, "name": ent.name, "entity_type": ent.entity_type.value}


@router.get("/api/projects/{project_id}/entities")
async def list_entities(project_id: str):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM entities WHERE project_id=?", (project_id,)).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["metadata"] = json.loads(d.get("metadata", "{}"))
        results.append(d)
    return results


# ── Relations ─────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/relations")
async def create_relation(project_id: str, body: RelationCreate):
    rel = Relation(
        project_id=project_id,
        source_entity_id=body.source_entity_id,
        target_entity_id=body.target_entity_id,
        relation_type=RelationType(body.relation_type),
        metadata=body.metadata,
        confidence=body.confidence,
    )
    conn = get_connection()
    conn.execute(
        "INSERT INTO relations (id, project_id, source_entity_id, target_entity_id, relation_type, metadata, confidence, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (rel.id, rel.project_id, rel.source_entity_id, rel.target_entity_id,
         rel.relation_type.value, json.dumps(rel.metadata), rel.confidence, rel.created_at),
    )
    conn.commit()
    conn.close()
    if context_engine:
        try:
            context_engine.add_relation(rel)
        except Exception:
            pass
    return {"id": rel.id, "relation_type": rel.relation_type.value}


# ── Graph ─────────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/graph")
async def get_graph(project_id: str, center_entity_id: str = None, radius: int = 2):
    if context_engine:
        try:
            if center_entity_id:
                return context_engine.get_subgraph(project_id, center_entity_id, radius)
            return context_engine.get_full_graph(project_id)
        except Exception as e:
            raise HTTPException(500, str(e))
    # Fallback: raw DB query
    conn = get_connection()
    entities = [dict(r) for r in conn.execute("SELECT * FROM entities WHERE project_id=?", (project_id,)).fetchall()]
    relations = [dict(r) for r in conn.execute("SELECT * FROM relations WHERE project_id=?", (project_id,)).fetchall()]
    conn.close()
    for e in entities:
        e["metadata"] = json.loads(e.get("metadata", "{}"))
    for r in relations:
        r["metadata"] = json.loads(r.get("metadata", "{}"))
    return {"entities": entities, "relations": relations}


# ── Changes ───────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/changes")
async def list_changes(project_id: str):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM change_events WHERE project_id=? ORDER BY created_at DESC LIMIT 100",
        (project_id,),
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["diff_data"] = json.loads(d.get("diff_data", "{}"))
        d["impacted_entity_ids"] = json.loads(d.get("impacted_entity_ids", "[]"))
        results.append(d)
    return results


# ── Impact ────────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/impact/{entity_id}")
async def get_impact(project_id: str, entity_id: str):
    if not context_engine:
        raise HTTPException(503, "Context engine unavailable")
    try:
        return context_engine.analyze_impact(project_id, entity_id)
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Agent ─────────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/agent/query")
async def agent_query(project_id: str, body: AgentQueryCreate):
    if not solus_agent:
        raise HTTPException(503, "Agent unavailable")
    try:
        result = await solus_agent.query(
            project_id=project_id,
            query=body.query,
            query_type=body.query_type,
            context_entity_ids=body.context_entity_ids,
        )
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Similar Issues ────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/similar-issues")
async def similar_issues(project_id: str, query: str = ""):
    if not memory_store:
        return []
    try:
        return memory_store.search(project_id, query)
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Issues ────────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/issues")
async def create_issue(project_id: str, body: IssueCreate):
    issue = Issue(
        project_id=project_id,
        title=body.title,
        description=body.description,
        related_entity_ids=body.related_entity_ids,
        reported_by=body.reported_by,
    )
    conn = get_connection()
    conn.execute(
        "INSERT INTO issues (id, project_id, title, description, status, related_entity_ids, reported_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (issue.id, issue.project_id, issue.title, issue.description, issue.status.value,
         json.dumps(issue.related_entity_ids), issue.reported_by, issue.created_at, issue.updated_at),
    )
    conn.commit()
    conn.close()
    return {"id": issue.id, "title": issue.title, "status": issue.status.value}


@router.get("/api/projects/{project_id}/issues")
async def list_issues(project_id: str):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM issues WHERE project_id=? ORDER BY created_at DESC", (project_id,)).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        d["related_entity_ids"] = json.loads(d.get("related_entity_ids", "[]"))
        results.append(d)
    return results


# ── Fixes ─────────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/fixes")
async def create_fix(project_id: str, body: FixCreate):
    fix = Fix(
        issue_id=body.issue_id,
        project_id=project_id,
        description=body.description,
        steps=body.steps,
        applied_by=body.applied_by,
    )
    conn = get_connection()
    conn.execute(
        "INSERT INTO fixes (id, issue_id, project_id, description, steps, applied_by, created_at) VALUES (?,?,?,?,?,?,?)",
        (fix.id, fix.issue_id, fix.project_id, fix.description,
         json.dumps(fix.steps), fix.applied_by, fix.created_at),
    )
    # Update issue status
    conn.execute("UPDATE issues SET status='resolved', updated_at=? WHERE id=?", (_now(), fix.issue_id))
    conn.commit()
    conn.close()

    # Store in memory for similar-issue search
    if memory_store:
        try:
            memory_store.store_issue_fix(project_id, body.issue_id, fix.description)
        except Exception:
            pass

    return {"id": fix.id, "issue_id": fix.issue_id}


# ── Live Bench ────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/live-bench/start")
async def start_live_bench(project_id: str, body: LiveBenchStart):
    if project_id in live_benches and live_benches[project_id].running:
        live_benches[project_id].stop()

    bench = LiveBench(project_id)
    live_benches[project_id] = bench

    # Build signal-entity map
    mapping = build_signal_entity_map(project_id)
    bench.set_signal_entity_map(mapping)

    if body.mode == "serial":
        asyncio.create_task(bench.start_serial(port=body.port, baud=body.baud))
    else:
        asyncio.create_task(bench.start_simulated())

    return {"started": True, "mode": body.mode, "project_id": project_id}


@router.post("/api/projects/{project_id}/live-bench/stop")
async def stop_live_bench(project_id: str):
    bench = live_benches.get(project_id)
    if bench:
        bench.stop()
        del live_benches[project_id]
    return {"stopped": True}


@router.post("/api/projects/{project_id}/live-bench/command")
async def send_command(project_id: str, body: SerialCommand):
    bench = live_benches.get(project_id)
    if not bench:
        raise HTTPException(404, "Live bench not running")
    bench.send_serial_command(body.command)
    return {"sent": body.command}


@router.get("/api/projects/{project_id}/live-bench/state")
async def get_bench_state(project_id: str):
    bench = live_benches.get(project_id)
    if not bench:
        return {"running": False}
    return bench.get_current_state()


@router.get("/api/projects/{project_id}/live-bench/logs")
async def get_bench_logs(project_id: str):
    bench = live_benches.get(project_id)
    if not bench:
        return {"report": "No live bench running", "anomaly_count": 0}
    return bench.get_anomaly_report()


@router.get("/api/serial-ports")
async def list_serial_ports():
    return LiveBench.list_serial_ports()


# ── WebSocket ─────────────────────────────────────────────────────────

@router.websocket("/ws/projects/{project_id}/live-bench")
async def ws_live_bench(websocket: WebSocket, project_id: str):
    await websocket.accept()

    if project_id not in ws_connections:
        ws_connections[project_id] = []
    ws_connections[project_id].append(websocket)

    bench = live_benches.get(project_id)
    queue: asyncio.Queue = asyncio.Queue()

    def on_data(msg):
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass

    if bench:
        bench.listeners.append(on_data)

    async def sender():
        try:
            while True:
                msg = await queue.get()
                await websocket.send_json(msg)
        except Exception:
            pass

    send_task = asyncio.create_task(sender())

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "send_serial" and bench:
                bench.send_serial_command(data.get("command", ""))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        send_task.cancel()
        if bench and on_data in bench.listeners:
            bench.listeners.remove(on_data)
        if project_id in ws_connections and websocket in ws_connections[project_id]:
            ws_connections[project_id].remove(websocket)


# ── Simulator ─────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/simulator/run")
async def run_simulation(project_id: str, body: SimRunRequest):
    if not simulator:
        raise HTTPException(503, "Simulator unavailable")
    result = await simulator.run_simulation(
        n_steps=body.n_steps, dt=body.dt, kp=body.kp, target_dist=body.target_dist,
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


@router.post("/api/projects/{project_id}/simulator/update-from-onshape")
async def update_sim_from_onshape(project_id: str, body: dict):
    if not simulator:
        raise HTTPException(503, "Simulator unavailable")
    simulator.update_from_onshape(body)
    return {"updated": True, "params": simulator.params}


@router.get("/api/projects/{project_id}/simulator/state")
async def get_sim_state(project_id: str):
    if not simulator:
        return {"available": False}
    return {
        "available": True,
        "mujoco": simulator.available,
        "params": simulator.params,
    }


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


# ── Arduino ───────────────────────────────────────────────────────────

@router.post("/api/arduino/flash")
async def flash_arduino(body: FlashRequest):
    # Stop serial if running on that port
    for pid, bench in list(live_benches.items()):
        if bench.serial_connection and bench.running:
            bench.stop()
            print(f"[routes] stopped live bench {pid} for flashing")

    result = await flasher.compile_and_upload(
        name=body.name, code=body.code, port=body.port, fqbn=body.fqbn,
    )

    if result["success"]:
        # Notify all WS connections
        for pid, conns in ws_connections.items():
            await broadcast_ws(pid, {"event": "code_flashed", "sketch": body.name})

    return result


@router.get("/api/arduino/boards")
async def list_arduino_boards():
    return flasher.list_boards()


@router.get("/api/arduino/available")
async def arduino_available():
    return {"available": flasher.is_available()}


# ── Camera ────────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/live-bench/camera")
async def camera_stream(project_id: str, ip: str = "192.168.4.1"):
    try:
        import httpx
    except ImportError:
        raise HTTPException(503, "httpx not installed")

    url = f"http://{ip}:81/stream"

    async def proxy():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("GET", url) as resp:
                async for chunk in resp.aiter_bytes(4096):
                    yield chunk

    return StreamingResponse(proxy(), media_type="multipart/x-mixed-replace; boundary=frame")


@router.get("/api/projects/{project_id}/live-bench/camera/status")
async def camera_status(project_id: str, ip: str = "192.168.4.1"):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0)) as client:
            resp = await client.get(f"http://{ip}")
            return {"reachable": resp.status_code == 200, "ip": ip}
    except Exception:
        return {"reachable": False, "ip": ip}


# ── Activity ──────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/activity")
async def get_activity(project_id: str):
    conn = get_connection()
    changes = conn.execute(
        "SELECT id, 'change' as type, entity_name as title, description, attributed_to, created_at FROM change_events WHERE project_id=? ORDER BY created_at DESC LIMIT 50",
        (project_id,),
    ).fetchall()
    issues = conn.execute(
        "SELECT id, 'issue' as type, title, description, reported_by as attributed_to, created_at FROM issues WHERE project_id=? ORDER BY created_at DESC LIMIT 50",
        (project_id,),
    ).fetchall()
    conn.close()

    activity = [dict(r) for r in changes] + [dict(r) for r in issues]
    activity.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return activity[:50]
