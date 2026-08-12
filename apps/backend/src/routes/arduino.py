"""Arduino firmware compile + flash via arduino-cli."""

from fastapi import APIRouter
from pydantic import BaseModel

from ..state import flasher, live_benches, ws_connections, broadcast_ws

router = APIRouter()


class FlashRequest(BaseModel):
    name: str
    code: str
    port: str = ""
    fqbn: str = "arduino:avr:uno"


@router.post("/api/arduino/flash")
async def flash_arduino(body: FlashRequest):
    # Stop serial if running on that port
    for pid, bench in list(live_benches.items()):
        if bench.serial_connection and bench.running:
            bench.stop()
            del live_benches[pid]
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
