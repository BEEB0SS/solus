"""Solus API routes, grouped by domain."""

from fastapi import APIRouter

from . import system, projects, sources, graph, intelligence, live_bench, simulator, arduino

router = APIRouter()
for mod in (system, projects, sources, graph, intelligence, live_bench, simulator, arduino):
    router.include_router(mod.router)
