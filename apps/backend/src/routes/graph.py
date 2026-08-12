"""Entities, relations, the context graph, changes, impact, and linking."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import Entity, Relation, EntityType, RelationType, SourceType

from ..database import get_connection
from ..state import context_engine, linker

router = APIRouter()


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
