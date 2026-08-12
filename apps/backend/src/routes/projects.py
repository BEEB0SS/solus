"""Project CRUD, team membership, and the activity feed."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import Project

from ..database import get_connection
from ..state import live_benches

router = APIRouter()


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    id: str = ""

class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

class AddTeamMemberRequest(BaseModel):
    name: str
    role: str = ""
    email: str = ""


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


@router.patch("/api/projects/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate):
    conn = get_connection()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Project not found")
    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if updates:
        now = datetime.utcnow().isoformat()
        sets = ", ".join(f"{k}=?" for k in updates)
        vals = list(updates.values()) + [now, project_id]
        conn.execute(f"UPDATE projects SET {sets}, updated_at=? WHERE id=?", vals)
        conn.commit()
    updated = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    return dict(updated)


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


@router.delete("/api/projects/{project_id}/team/{member_id}")
async def remove_team_member(project_id: str, member_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM team_members WHERE id=? AND project_id=?", (member_id, project_id))
    conn.commit()
    conn.close()
    return {"ok": True}


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
