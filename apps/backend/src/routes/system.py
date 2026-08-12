"""Health check."""

from fastapi import APIRouter

from ..state import context_engine, solus_agent, simulator

router = APIRouter()


@router.get("/api/health")
async def health():
    return {
        "status": "ok",
        "version": "0.2.0",
        "context_engine": context_engine is not None,
        "agent": solus_agent is not None,
        "simulator": simulator is not None,
    }
