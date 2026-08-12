"""Source connections and the sync pipeline (GitHub / KiCad / Onshape)."""

import json
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import (
    SourceConnection, ChangeEvent,
    EntityType, RelationType, SourceType, ChangeType,
    _now,
)

from ..database import get_connection
from ..state import context_engine, linker, broadcast_ws

router = APIRouter()


class SourceCreate(BaseModel):
    source_type: str
    name: str
    config: dict = {}


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
            from ..connectors.github import GitHubConnector
            path_or_url = config.get("url") or config.get("path", "")
            connector = GitHubConnector(path_or_url, project_id)
        elif source_type == "kicad":
            from ..connectors.kicad import KiCadConnector
            connector = KiCadConnector(config["path"], project_id)
        elif source_type == "onshape":
            from ..connectors.onshape import OnshapeConnector
            doc_id = config.get("document_id") or config.get("url", "")
            connector = OnshapeConnector(
                doc_id,
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

        # Map connector entity IDs to actual DB entity IDs (for relation remapping)
        id_remap: dict[str, str] = {}

        for ent in ingested.get("entities", []):
            if ent.source_ref and ent.source_ref in existing_by_ref:
                # Update existing entity
                old = existing_by_ref[ent.source_ref]
                id_remap[ent.id] = old.id
                context_engine.update_entity(old.id, {
                    "name": ent.name,
                    "description": ent.description,
                    "metadata": ent.metadata,
                })
                entities_updated += 1
            else:
                id_remap[ent.id] = ent.id
                context_engine.create_entity(ent)
                entities_created += 1

        # 7. Create relations (remap IDs and skip duplicates)
        existing_rel_pairs = set()
        for r in context_engine.get_relations_by_project(project_id):
            existing_rel_pairs.add((r.source_entity_id, r.target_entity_id, r.relation_type.value))

        for rel in ingested.get("relations", []):
            rel.source_entity_id = id_remap.get(rel.source_entity_id, rel.source_entity_id)
            rel.target_entity_id = id_remap.get(rel.target_entity_id, rel.target_entity_id)
            key = (rel.source_entity_id, rel.target_entity_id,
                   rel.relation_type.value if hasattr(rel.relation_type, 'value') else rel.relation_type)
            if key not in existing_rel_pairs:
                context_engine.create_relation(rel)
                existing_rel_pairs.add(key)

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
