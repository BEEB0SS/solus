"""Live bench control, device discovery, the telemetry WebSocket, and the camera proxy."""

import asyncio

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..live_bench import LiveBench
from ..state import live_benches, ws_connections, discovery, linker, build_signal_entity_map

router = APIRouter()


class LiveBenchStart(BaseModel):
    mode: str = "simulated"
    port: str = ""
    baud: int = 9600

class SerialCommand(BaseModel):
    command: str


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
