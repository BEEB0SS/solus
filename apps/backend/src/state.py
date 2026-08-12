"""
Shared application state — singletons with graceful degradation, live bench
registry, WebSocket connections, and helpers used across routers.
"""

from fastapi import WebSocket

from models import EntityType

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
