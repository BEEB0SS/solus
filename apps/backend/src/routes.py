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

try:
    from .cross_domain_linker import CrossDomainLinker, DeviceDiscovery
    linker = CrossDomainLinker(context_engine) if context_engine else None
    discovery = DeviceDiscovery(context_engine) if context_engine else None
except Exception as e:
    print(f"[warn] Linker/Discovery unavailable: {e}")
    linker = None
    discovery = None

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
        entities = context_engine.get_entities_by_project(project_id)
        for e in entities:
            etype = e.entity_type.value if isinstance(e.entity_type, EntityType) else e.entity_type
            eid = e.id
            name = e.name.lower()

            if "motor" in name or (etype == "electrical_part" and "tb6612" in name):
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
    id: str = ""

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

class AddTeamMemberRequest(BaseModel):
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
    if body.id:
        p.id = body.id
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
async def add_team_member(project_id: str, req: AddTeamMemberRequest):
    conn = get_connection()
    member_id = str(__import__('uuid').uuid4())
    now = __import__('datetime').datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO team_members (id, project_id, name, role, email) VALUES (?,?,?,?,?)",
        (member_id, project_id, req.name, req.role, req.email),
    )
    conn.commit()
    conn.close()

    # Broadcast team activity
    for pid, bench in live_benches.items():
        if pid == project_id:
            for listener in bench.listeners:
                try:
                    await listener({"event": "team_activity", "user": req.name, "action": "joined the team"})
                except:
                    pass

    return {"id": member_id, "project_id": project_id, "name": req.name, "role": req.role, "email": req.email}


@router.get("/api/projects/{project_id}/team")
async def get_team(project_id: str):
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
    return {
        "id": sc.id,
        "project_id": sc.project_id,
        "source_type": sc.source_type.value,
        "name": sc.name,
        "config": sc.config,
        "status": sc.status,
        "last_synced_at": sc.last_synced_at,
    }


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
    # 1. Load source from DB
    conn = get_connection()
    row = conn.execute("SELECT * FROM source_connections WHERE id=? AND project_id=?",
                       (source_id, project_id)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Source not found")
    source = dict(row)
    config = json.loads(source.get("config", "{}"))
    source_type = source["source_type"]

    # 2. Dispatch to connector
    connector = None
    try:
        if source_type == "github":
            from .connectors.github import GitHubConnector
            path_or_url = config.get("url") or config.get("path", "")
            connector = GitHubConnector(path_or_url, project_id)
        elif source_type == "kicad":
            from .connectors.kicad import KiCadConnector
            connector = KiCadConnector(config["path"], project_id)
        elif source_type == "onshape":
            from .connectors.onshape import OnshapeConnector
            connector = OnshapeConnector(
                config["document_id"],
                config.get("workspace_id", ""),
                project_id,
                os.environ.get("ONSHAPE_ACCESS_KEY", ""),
                os.environ.get("ONSHAPE_SECRET_KEY", ""),
            )
    except (ImportError, KeyError) as e:
        raise HTTPException(500, f"Connector error: {e}")

    if not connector:
        raise HTTPException(400, f"Unknown source type: {source_type}")

    # 3. Run ingest (onshape uses .sync())
    try:
        if source_type == "onshape":
            ingested = connector.sync()
        else:
            ingested = connector.ingest()
    except Exception as e:
        raise HTTPException(500, f"Sync failed: {e}")

    new_data = {"items": ingested.get("items", [])}
    entities_created = 0
    entities_updated = 0
    changes = []

    if context_engine:
        # 4. Snapshot: get previous, create new
        old_snapshot = context_engine.get_latest_snapshot(source_id)
        new_snapshot = context_engine.create_snapshot(source_id, project_id, new_data)

        # 5. Compute diff if previous snapshot exists
        diffs = []
        if old_snapshot:
            diffs = context_engine.compute_diff(old_snapshot.data, new_data)

        # 6. Upsert entities — check if source_ref already exists
        existing_entities = context_engine.get_entities_by_project(project_id)
        existing_by_ref = {}
        for e in existing_entities:
            if e.source_ref:
                existing_by_ref[e.source_ref] = e

        for ent in ingested.get("entities", []):
            if ent.source_ref and ent.source_ref in existing_by_ref:
                # Update existing entity
                old = existing_by_ref[ent.source_ref]
                context_engine.update_entity(old.id, {
                    "name": ent.name,
                    "description": ent.description,
                    "metadata": ent.metadata,
                })
                entities_updated += 1
            else:
                context_engine.create_entity(ent)
                entities_created += 1

        # 7. Create relations
        for rel in ingested.get("relations", []):
            context_engine.create_relation(rel)

        # 8. Log change events from diffs
        for diff in diffs:
            change_type = {"added": ChangeType.ADDED, "modified": ChangeType.MODIFIED,
                           "removed": ChangeType.REMOVED}.get(diff["type"], ChangeType.MODIFIED)
            item = diff.get("new") or diff.get("old") or {}
            ce = ChangeEvent(
                project_id=project_id,
                source_connection_id=source_id,
                change_type=change_type,
                entity_id=item.get("ref", ""),
                entity_name=item.get("name", item.get("ref", "")),
                description=f"{diff['type']} via {source_type} sync",
                diff_data={"changed_fields": diff.get("changed_fields", [])},
                attributed_to=source_type,
            )
            context_engine.log_change_event(ce)
            changes.append({
                "type": diff["type"],
                "ref": diff.get("ref", ""),
                "changed_fields": diff.get("changed_fields", []),
            })
    else:
        # No context engine — direct DB inserts
        conn = get_connection()
        for ent in ingested.get("entities", []):
            conn.execute(
                "INSERT OR IGNORE INTO entities (id, project_id, entity_type, name, description, metadata, source, source_ref, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ent.id, ent.project_id,
                 ent.entity_type.value if isinstance(ent.entity_type, EntityType) else ent.entity_type,
                 ent.name, ent.description, json.dumps(ent.metadata),
                 ent.source.value if isinstance(ent.source, SourceType) else ent.source,
                 ent.source_ref, ent.created_at, ent.updated_at),
            )
            entities_created += 1
        for rel in ingested.get("relations", []):
            conn.execute(
                "INSERT OR IGNORE INTO relations (id, project_id, source_entity_id, target_entity_id, relation_type, metadata, confidence, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (rel.id, rel.project_id, rel.source_entity_id, rel.target_entity_id,
                 rel.relation_type.value if isinstance(rel.relation_type, RelationType) else rel.relation_type,
                 json.dumps(rel.metadata), rel.confidence, rel.created_at),
            )
        conn.commit()
        conn.close()

    # 9. Update source last_synced_at
    now = _now()
    conn = get_connection()
    conn.execute("UPDATE source_connections SET last_synced_at=?, status='connected' WHERE id=?",
                 (now, source_id))
    conn.commit()
    conn.close()

    # 10. Run cross-domain linking
    link_results = {}
    if linker:
        try:
            link_results = linker.link_project(project_id)
        except Exception as e:
            print(f"[linker] error: {e}")

    # Broadcast activity
    await broadcast_ws(project_id, {
        "event": "team_activity",
        "source_type": source_type,
        "entities_created": entities_created,
        "entities_updated": entities_updated,
    })

    return {
        "success": True,
        "entities_created": entities_created,
        "entities_updated": entities_updated,
        "relations_linked": sum(
            v.get("relations_created", 0) for v in link_results.values() if isinstance(v, dict)
        ),
        "descriptions_enriched": link_results.get("enriched", {}).get("enriched", 0) if isinstance(link_results.get("enriched"), dict) else 0,
        "changes": changes,
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
    if context_engine:
        context_engine.create_entity(ent)
    else:
        conn = get_connection()
        conn.execute(
            "INSERT INTO entities (id, project_id, entity_type, name, description, metadata, source, source_ref, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ent.id, ent.project_id, ent.entity_type.value, ent.name, ent.description,
             json.dumps(ent.metadata), ent.source.value, ent.source_ref, ent.created_at, ent.updated_at),
        )
        conn.commit()
        conn.close()
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
    if context_engine:
        context_engine.create_relation(rel)
    else:
        conn = get_connection()
        conn.execute(
            "INSERT INTO relations (id, project_id, source_entity_id, target_entity_id, relation_type, metadata, confidence, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (rel.id, rel.project_id, rel.source_entity_id, rel.target_entity_id,
             rel.relation_type.value, json.dumps(rel.metadata), rel.confidence, rel.created_at),
        )
        conn.commit()
        conn.close()
    return {"id": rel.id, "relation_type": rel.relation_type.value}


# ── Graph ─────────────────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/graph")
async def get_graph(project_id: str, center_entity_id: str = None, radius: int = 2):
    if context_engine:
        try:
            return context_engine.get_subgraph(project_id, center_entity_id, radius)
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
    if context_engine:
        return context_engine.get_recent_changes(project_id)
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
        return context_engine.analyze_impact(entity_id, project_id)
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Cross-Domain Linker ───────────────────────────────────────────────

@router.post("/api/projects/{project_id}/link")
async def link_project(project_id: str):
    """Re-run cross-domain linking for a project."""
    if not linker:
        raise HTTPException(503, "Linker unavailable")
    try:
        result = linker.link_project(project_id)
        return result
    except Exception as e:
        raise HTTPException(500, f"Linking failed: {e}")


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


@router.post("/api/projects/{project_id}/live-bench/discover")
async def discover_devices(project_id: str):
    """Analyze current telemetry to auto-discover connected peripherals and build the graph."""
    bench = live_benches.get(project_id)
    if not bench or not bench.running:
        raise HTTPException(400, "Live bench not running — connect first")

    state = bench.get_current_state()
    signals = state.get("signals", {})
    if not signals:
        raise HTTPException(400, "No signals received yet — wait a few seconds after connecting")

    if not discovery:
        raise HTTPException(503, "Device discovery unavailable")

    # Get port info if serial connection
    port_info = None
    if bench.serial_connection:
        port_info = {
            "device": bench.serial_connection.port,
            "is_arduino": True,
        }

    try:
        result = discovery.discover_from_telemetry(project_id, signals, port_info)

        # Also run cross-domain linker after discovery
        if linker:
            try:
                link_result = linker.link_project(project_id)
                result["cross_domain_links"] = link_result
            except Exception as e:
                print(f"[linker] error after discovery: {e}")

        # Rebuild signal-entity map now that we have new entities
        mapping = build_signal_entity_map(project_id)
        bench.set_signal_entity_map(mapping)

        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Discovery failed: {e}")


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
async def get_activity(project_id: str, limit: int = 50):
    conn = get_connection()
    activity = []

    # Changes
    changes = conn.execute(
        "SELECT * FROM change_events WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit)
    ).fetchall()
    for c in changes:
        cd = dict(c)
        activity.append({
            "type": "change",
            "user": cd.get("attributed_to", "System"),
            "description": cd.get("description", f"Changed {cd.get('entity_name', 'unknown')}"),
            "timestamp": cd.get("created_at", ""),
        })

    # Issues
    issues = conn.execute(
        "SELECT * FROM issues WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit)
    ).fetchall()
    for i in issues:
        d = dict(i)
        activity.append({
            "type": "issue",
            "user": d.get("reported_by", "Unknown"),
            "description": d.get("title", ""),
            "timestamp": d.get("created_at", ""),
        })

    conn.close()
    activity.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return activity[:limit]
