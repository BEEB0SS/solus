"""AI agent queries, issues, fixes, and similar-issue search."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models import Issue, Fix, AgentQuery, _now

from ..database import get_connection
from ..state import solus_agent, memory_store

router = APIRouter()


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


# ── Agent ─────────────────────────────────────────────────────────────

@router.post("/api/projects/{project_id}/agent/query")
async def agent_query(project_id: str, body: AgentQueryCreate):
    if not solus_agent:
        return {"query_id": "", "response_text": "Agent unavailable — check backend logs.", "confidence": 0.0}
    try:
        aq = AgentQuery(
            project_id=project_id,
            query=body.query,
            query_type=body.query_type,
            context_entity_ids=body.context_entity_ids,
        )
        result = await solus_agent.query(aq)
        return result
    except Exception as e:
        return {"query_id": "", "response_text": f"Agent error: {e}", "confidence": 0.0}


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
