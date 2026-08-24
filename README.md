# Solus

**An AI-powered debugging workspace for robotics.** Solus connects to a real robot, streams live telemetry, detects behavioral bugs through pattern analysis, and uses an AI agent that reasons over the *whole* system — firmware, electronics, mechanical design, and simulation — to diagnose the root cause and flash a fix.

This is the first iteration of Solus, built as our submission to the **YC x Google DeepMind hackathon**.

## Why

Robotics bugs rarely live in one domain. A robot that oscillates in front of a wall might have a bad PID gain (code), a miswired motor driver (electronics), or a wheel mounted backwards (mechanical). Traditional debuggers only see one of those layers. Solus builds a **context graph** that links code symbols, schematic components, and CAD parts into one model, so when telemetry looks wrong, the diagnosis can trace across all three.

## What it does

1. **Live Bench** — connects to the robot over serial (or a built-in simulated mode), streams telemetry signals (motor PWM, ultrasonic distance, PID error, battery, IMU) over WebSocket to the UI, and auto-discovers which hardware devices are present from the signals themselves.
2. **Behavioral anomaly detection** — goes beyond simple thresholds:
   - **Oscillation**: counts motor sign-changes in a 2-second window
   - **PID non-convergence**: variance of distance/PID error over 3 seconds
   - **Motor anti-correlation**: Pearson correlation between left/right motor commands
   - **Energy waste**: average |motor output| over time
3. **Context Model** — a force-directed graph of entities (functions, ICs, nets, CAD parts) and relations, built by connectors that parse a Git repo, a KiCad schematic, and an Onshape CAD document. A cross-domain linker matches pin numbers in code to schematic nets to physical components, so an anomaly on `motor_left` traces back to the TB6612FNG driver on the board.
4. **Intelligence** — a Claude-powered agent that receives the anomaly report *plus* the relevant slice of the context graph, diagnoses the fault, proposes a code fix, and can compile and flash corrected firmware to the robot via `arduino-cli` — without leaving the app.
5. **Simulator** — a MuJoCo digital twin of the robot, with geometry synced from Onshape, that runs the same PID loop so simulated and real telemetry can be compared side by side.

## Architecture

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│  Desktop app (Electron)     │        │  Backend (FastAPI, :8000)    │
│  React + TS + Vite (:5173)  │◄──────►│                              │
│                             │  REST  │  routes/    domain routers   │
│  Workspace   — projects     │   +    │  context_engine  graph CRUD  │
│  Live Bench  — telemetry    │   WS   │  live_bench   serial + anomaly│
│  Context     — graph viz    │        │  simulator    MuJoCo twin    │
│  Intelligence— AI agent     │        │  agent/       Claude agent   │
└─────────────────────────────┘        │  connectors/  GitHub/KiCad/  │
                                       │               Onshape        │
                                       │  SQLite + shared dataclasses │
                                       └──────────────┬───────────────┘
                                                      │ serial 9600 baud
                                              ┌───────▼────────┐
                                              │ Elegoo V4 robot │
                                              │ (Arduino UNO)   │
                                              └────────────────┘
```

- **Backend:** Python / FastAPI at `localhost:8000` (`apps/backend/src/`)
- **Frontend:** React + TypeScript + Vite, wrapped in Electron (`apps/desktop/src/renderer/`)
- **Shared types:** Python dataclasses acting as the API contract (`packages/shared-types/src/models.py`)
- **Database:** SQLite (`apps/backend/src/database.py`)
- **AI:** Anthropic Claude via the `anthropic` SDK

### Module map

| Path | Purpose |
|------|---------|
| `apps/backend/src/routes/` | API routers by domain: projects, sources, graph, live bench, simulator, intelligence, arduino |
| `apps/backend/src/state.py` | Shared singletons (engine, agent, simulator) with graceful degradation |
| `apps/backend/src/context_engine.py` | Graph CRUD, impact analysis, snapshots |
| `apps/backend/src/live_bench.py` | Serial telemetry + behavioral anomaly detection |
| `apps/backend/src/cross_domain_linker.py` | Pin/net/part matching across code, schematic, CAD |
| `apps/backend/src/simulator.py` | MuJoCo wrapper + PID loop |
| `apps/backend/src/arduino_flasher.py` | Compile + upload via arduino-cli |
| `apps/backend/src/agent/` | Claude agent + TF-IDF memory of past issues |
| `apps/backend/src/connectors/` | GitHub, KiCad, Onshape parsers |
| `packages/shared-types/src/models.py` | All data models — the contract |
| `apps/desktop/src/renderer/components/` | One folder per tab: workspace, live-bench, context-model, intelligence |
| `apps/desktop/src/renderer/stores/projectStore.ts` | Zustand state |

## Getting started

No robot required — the Live Bench has a **simulated mode** that generates realistic telemetry (including the oscillation bug) so the full pipeline runs on any machine.

### Backend

```bash
cd apps/backend
./run.sh
```

The script creates the venv and installs `requirements.txt` on first run, then starts uvicorn on :8000 from the venv. (Equivalent manual steps: `python3 -m venv .venv`, `.venv/bin/pip install -r requirements.txt`, `.venv/bin/uvicorn src.main:app --port 8000` — but always the venv's uvicorn, see the troubleshooting note below.)

### Frontend

```bash
cd apps/desktop
pnpm install
pnpm dev:web        # browser at http://localhost:5173
# or: pnpm dev      # Electron shell
```

### Environment

Copy `.env.example` to `.env` at the repo root:

- `CLAUDE_API_KEY` (or `ANTHROPIC_API_KEY`) — enables the Intelligence agent
- `ONSHAPE_ACCESS_KEY` / `ONSHAPE_SECRET_KEY` — enables CAD sync (optional)

Everything degrades gracefully: without keys the agent endpoints report they're unconfigured, and without `mujoco`/`pyserial` installed the simulator falls back to a kinematic stub and serial features disable themselves.

> **Troubleshooting:** if the Live Bench connection dot never turns green and the vite console logs `ws proxy error: write EPIPE`, the backend is running under a Python environment without the `websockets` package (uvicorn then answers WebSocket upgrades with plain 404s). Start it from the project venv: `.venv/bin/uvicorn src.main:app --port 8000`.

## Testing

Unit tests cover the pure logic — the four behavioral anomaly detectors (fed synthetic telemetry buffers), the snapshot diff engine, and the KiCad schematic parser (run against the real Elegoo schematic in `demo-assets/` as a fixture):

```bash
cd apps/backend
.venv/bin/pytest
```

An end-to-end script walks the whole flow against a live server — create project → sync `demo-assets/` sources → build graph → start simulated bench → detect anomalies → query the agent:

```bash
python3 tests/test_demo_flow.py   # backend must be running on :8000
```

The frontend typechecks with `pnpm typecheck` (also aliased as `pnpm test`) and bundles with `pnpm build` from `apps/desktop`.

## The demo

The repo ships a complete reproduction of a real debugging session (`demo-assets/`):

1. Flash `arduino-sketches/buggy/buggy.ino` — its PID gains are wrong (`KP=50, KD=0`), so the robot oscillates violently in front of obstacles.
2. Live Bench detects the oscillation pattern (motor sign-flips) and non-converging PID error, and maps the anomaly to the motor driver and control function in the context graph.
3. The agent diagnoses the gain problem from telemetry + graph + source, and proposes the fix.
4. Flash `arduino-sketches/fixed/fixed.ino` (`KP=2, KD=0.5`) and watch the telemetry settle.

## Hardware

Built around the **Elegoo V4 Smart Robot Car** (Arduino UNO):

| Component | Details |
|-----------|---------|
| Serial | CH340 at 9600 baud (`/dev/ttyUSB0`) |
| Motor driver | TB6612FNG — PWMA=5, AIN1=7, PWMB=6, BIN1=8, STBY=3 |
| Ultrasonic | HC-SR04 — TRIG=13, ECHO=12 |
| Servo | SG90 on pin 10 |
| Camera | ESP32-WROVER streaming over its own WiFi AP (192.168.4.1) |
| Drive | 4 DC motors, left/right pairs on the two TB6612 channels |

Two hard-won implementation details, for the curious: the Arduino resets when the serial port opens (so the backend sleeps 3s and flushes before reading), and serial reads run through `loop.run_in_executor` — a synchronous `readline` would block the asyncio event loop and starve the WebSocket.

## License

MIT — see [LICENSE](LICENSE).
