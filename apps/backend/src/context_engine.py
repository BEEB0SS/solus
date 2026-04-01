"""
Solus Context Engine.
Graph CRUD, impact analysis, diff computation, snapshots.
"""

import json
import os
import sys
from collections import deque
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'packages', 'shared-types', 'src'))
sys.path.insert(0, os.path.dirname(__file__))

from models import Entity, Relation, Snapshot, ChangeEvent, EntityType, RelationType, SourceType, ChangeType
from database import get_connection


class ContextEngine:

    # ── Entity CRUD ───────────────────────────────────────────────────

    def create_entity(self, entity: Entity) -> Entity:
        conn = get_connection()
        conn.execute(
            """INSERT INTO entities (id, project_id, entity_type, name, description, metadata, source, source_ref, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entity.id, entity.project_id, entity.entity_type.value if isinstance(entity.entity_type, EntityType) else entity.entity_type,
             entity.name, entity.description, json.dumps(entity.metadata),
             entity.source.value if isinstance(entity.source, SourceType) else entity.source,
             entity.source_ref, entity.created_at, entity.updated_at)
        )
        conn.commit()
        conn.close()
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        conn = get_connection()
        row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
        conn.close()
        if not row:
            return None
        return Entity(
            id=row["id"], project_id=row["project_id"],
            entity_type=EntityType(row["entity_type"]), name=row["name"],
            description=row["description"], metadata=json.loads(row["metadata"]),
            source=SourceType(row["source"]), source_ref=row["source_ref"],
            created_at=row["created_at"], updated_at=row["updated_at"]
        )

    def get_entities_by_project(self, project_id: str, entity_type: str = None) -> list[Entity]:
        conn = get_connection()
        if entity_type:
            rows = conn.execute(
                "SELECT * FROM entities WHERE project_id = ? AND entity_type = ?",
                (project_id, entity_type)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM entities WHERE project_id = ?", (project_id,)
            ).fetchall()
        conn.close()
        return [
            Entity(
                id=r["id"], project_id=r["project_id"],
                entity_type=EntityType(r["entity_type"]), name=r["name"],
                description=r["description"], metadata=json.loads(r["metadata"]),
                source=SourceType(r["source"]), source_ref=r["source_ref"],
                created_at=r["created_at"], updated_at=r["updated_at"]
            ) for r in rows
        ]

    def update_entity(self, entity_id: str, updates: dict) -> Entity:
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        updates["updated_at"] = now
        set_clauses = []
        values = []
        for key, val in updates.items():
            set_clauses.append(f"{key} = ?")
            if key == "metadata":
                values.append(json.dumps(val))
            elif key == "entity_type" and isinstance(val, EntityType):
                values.append(val.value)
            elif key == "source" and isinstance(val, SourceType):
                values.append(val.value)
            else:
                values.append(val)
        values.append(entity_id)
        conn.execute(
            f"UPDATE entities SET {', '.join(set_clauses)} WHERE id = ?", values
        )
        conn.commit()
        conn.close()
        return self.get_entity(entity_id)

    def delete_entity(self, entity_id: str):
        conn = get_connection()
        conn.execute(
            "DELETE FROM relations WHERE source_entity_id = ? OR target_entity_id = ?",
            (entity_id, entity_id)
        )
        conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
        conn.commit()
        conn.close()

    # ── Relation CRUD ─────────────────────────────────────────────────

    def create_relation(self, relation: Relation) -> Relation:
        conn = get_connection()
        conn.execute(
            """INSERT INTO relations (id, project_id, source_entity_id, target_entity_id, relation_type, metadata, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (relation.id, relation.project_id, relation.source_entity_id,
             relation.target_entity_id,
             relation.relation_type.value if isinstance(relation.relation_type, RelationType) else relation.relation_type,
             json.dumps(relation.metadata), relation.confidence, relation.created_at)
        )
        conn.commit()
        conn.close()
        return relation

    def get_relations_for_entity(self, entity_id: str) -> list[Relation]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM relations WHERE source_entity_id = ? OR target_entity_id = ?",
            (entity_id, entity_id)
        ).fetchall()
        conn.close()
        return [self._row_to_relation(r) for r in rows]

    def get_relations_by_project(self, project_id: str) -> list[Relation]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM relations WHERE project_id = ?", (project_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_relation(r) for r in rows]

    def _row_to_relation(self, r) -> Relation:
        return Relation(
            id=r["id"], project_id=r["project_id"],
            source_entity_id=r["source_entity_id"],
            target_entity_id=r["target_entity_id"],
            relation_type=RelationType(r["relation_type"]),
            metadata=json.loads(r["metadata"]),
            confidence=r["confidence"], created_at=r["created_at"]
        )

    # ── Snapshots ─────────────────────────────────────────────────────

    def create_snapshot(self, source_connection_id: str, project_id: str, data: dict) -> Snapshot:
        snap = Snapshot(source_connection_id=source_connection_id, project_id=project_id, data=data)
        conn = get_connection()
        conn.execute(
            """INSERT INTO snapshots (id, source_connection_id, project_id, data, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (snap.id, snap.source_connection_id, snap.project_id,
             json.dumps(snap.data), snap.created_at)
        )
        conn.commit()
        conn.close()
        return snap

    def get_latest_snapshot(self, source_connection_id: str) -> Snapshot | None:
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM snapshots WHERE source_connection_id = ? ORDER BY created_at DESC LIMIT 1",
            (source_connection_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return Snapshot(
            id=row["id"], source_connection_id=row["source_connection_id"],
            project_id=row["project_id"], data=json.loads(row["data"]),
            created_at=row["created_at"]
        )

    # ── Diff ──────────────────────────────────────────────────────────

    def compute_diff(self, old_data: dict, new_data: dict) -> list[dict]:
        old_items = {item["ref"]: item for item in old_data.get("items", [])}
        new_items = {item["ref"]: item for item in new_data.get("items", [])}
        diffs = []

        for ref, new_item in new_items.items():
            if ref not in old_items:
                diffs.append({"type": "added", "ref": ref, "old": None, "new": new_item, "changed_fields": []})
            else:
                old_item = old_items[ref]
                changed = [k for k in set(list(old_item.keys()) + list(new_item.keys()))
                           if old_item.get(k) != new_item.get(k) and k != "ref"]
                if changed:
                    diffs.append({"type": "modified", "ref": ref, "old": old_item, "new": new_item, "changed_fields": changed})

        for ref in old_items:
            if ref not in new_items:
                diffs.append({"type": "removed", "ref": ref, "old": old_items[ref], "new": None, "changed_fields": []})

        return diffs

    # ── Impact Analysis (BFS) ─────────────────────────────────────────

    def analyze_impact(self, entity_id: str, project_id: str, max_hops: int = 2) -> dict:
        source = self.get_entity(entity_id)
        source_name = source.name if source else ""
        relations = self.get_relations_by_project(project_id)

        adj: dict[str, list[tuple[str, str]]] = {}
        for rel in relations:
            adj.setdefault(rel.source_entity_id, []).append((rel.target_entity_id, rel.relation_type.value))
            adj.setdefault(rel.target_entity_id, []).append((rel.source_entity_id, rel.relation_type.value))

        visited = {entity_id}
        queue = deque()
        for neighbor_id, rel_type in adj.get(entity_id, []):
            if neighbor_id not in visited:
                queue.append((neighbor_id, rel_type, 1, [entity_id, neighbor_id]))
                visited.add(neighbor_id)

        impacted = []
        while queue:
            nid, rtype, depth, path = queue.popleft()
            ent = self.get_entity(nid)
            impacted.append({
                "entity_id": nid,
                "entity_name": ent.name if ent else "",
                "entity_type": ent.entity_type.value if ent else "",
                "relation_type": rtype,
                "depth": depth,
                "path": path
            })
            if depth < max_hops:
                for next_id, next_rtype in adj.get(nid, []):
                    if next_id not in visited:
                        visited.add(next_id)
                        queue.append((next_id, next_rtype, depth + 1, path + [next_id]))

        return {
            "source_entity_id": entity_id,
            "source_entity_name": source_name,
            "impacted": impacted,
            "total_impacted": len(impacted)
        }

    # ── Subgraph ──────────────────────────────────────────────────────

    def get_subgraph(self, project_id: str, center_entity_id: str = None, radius: int = 2) -> dict:
        if center_entity_id:
            relations = self.get_relations_by_project(project_id)
            adj: dict[str, list[str]] = {}
            for rel in relations:
                adj.setdefault(rel.source_entity_id, []).append(rel.target_entity_id)
                adj.setdefault(rel.target_entity_id, []).append(rel.source_entity_id)

            visited = {center_entity_id}
            queue = deque([(center_entity_id, 0)])
            while queue:
                nid, depth = queue.popleft()
                if depth < radius:
                    for neighbor in adj.get(nid, []):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append((neighbor, depth + 1))

            entity_ids = visited
            entities = [self.get_entity(eid) for eid in entity_ids]
            entities = [e for e in entities if e is not None]
            rels = [r for r in relations if r.source_entity_id in entity_ids and r.target_entity_id in entity_ids]
        else:
            entities = self.get_entities_by_project(project_id)
            rels = self.get_relations_by_project(project_id)

        return {
            "entities": [
                {"id": e.id, "entity_type": e.entity_type.value, "name": e.name,
                 "description": e.description, "metadata": e.metadata,
                 "source": e.source.value, "source_ref": e.source_ref}
                for e in entities
            ],
            "relations": [
                {"id": r.id, "source_entity_id": r.source_entity_id,
                 "target_entity_id": r.target_entity_id,
                 "relation_type": r.relation_type.value,
                 "confidence": r.confidence, "metadata": r.metadata}
                for r in rels
            ]
        }

    # ── Change Events ─────────────────────────────────────────────────

    def log_change_event(self, event: ChangeEvent) -> ChangeEvent:
        conn = get_connection()
        conn.execute(
            """INSERT INTO change_events (id, project_id, source_connection_id, change_type, entity_id, entity_name,
               description, diff_data, impacted_entity_ids, attributed_to, acknowledged, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event.id, event.project_id, event.source_connection_id,
             event.change_type.value if isinstance(event.change_type, ChangeType) else event.change_type,
             event.entity_id, event.entity_name, event.description,
             json.dumps(event.diff_data), json.dumps(event.impacted_entity_ids),
             event.attributed_to, 1 if event.acknowledged else 0, event.created_at)
        )
        conn.commit()
        conn.close()
        return event

    def get_recent_changes(self, project_id: str, limit: int = 20) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM change_events WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit)
        ).fetchall()
        conn.close()
        return [
            {
                "id": r["id"], "project_id": r["project_id"],
                "source_connection_id": r["source_connection_id"],
                "change_type": r["change_type"], "entity_id": r["entity_id"],
                "entity_name": r["entity_name"], "description": r["description"],
                "diff_data": json.loads(r["diff_data"]),
                "impacted_entity_ids": json.loads(r["impacted_entity_ids"]),
                "attributed_to": r["attributed_to"],
                "acknowledged": bool(r["acknowledged"]),
                "created_at": r["created_at"]
            } for r in rows
        ]
