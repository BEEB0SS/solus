# CLAUDE.md — Read by every Claude Code agent automatically

## What This Project Is

Solus is a robotics development workspace. It connects to a real robot, streams live telemetry, detects bugs via behavioral pattern analysis, and uses an AI agent to diagnose and fix issues by reasoning over the full system context (code + electronics + hardware).

## Architecture

- **Backend:** Python FastAPI at localhost:8000 (`apps/backend/src/`)
- **Frontend:** React + TypeScript + Vite at localhost:5173 (`apps/desktop/src/renderer/`)
- **Shared Types:** Python dataclasses (`packages/shared-types/src/models.py`)
- **Database:** SQLite via `apps/backend/src/database.py`
- **AI:** Google Gemini 2.0 Flash via `google-generativeai` SDK
- **Demo Assets:** KiCad schematic, Arduino sketches (`demo-assets/`)

## The Robot

Elegoo V4 Smart Robot Car:
- Serial: `/dev/ttyUSB0` at 9600 baud (CH340 chip). NOT /dev/ttyACM0 (that's the PC monitor).
- Motor driver: TB6612FNG (PWMA=5, AIN1=7, PWMB=6, BIN1=8, STBY=3)
- Ultrasonic: HC-SR04 (TRIG=13, ECHO=12)
- Servo: SG90 on pin 10
- Camera: ESP32-WROVER on WiFi AP 192.168.4.1
- 4 wheels, 4 DC motors (left pair + right pair wired to 2 TB6612 channels)
- Arduino resets when serial opens — always sleep 3s + flush buffer before reading

## Critical Technical Rules

1. **Serial reads MUST use `await loop.run_in_executor(None, ser.readline)`** — synchronous readline blocks the entire asyncio event loop and prevents WebSocket from working.

2. **Default baud is 9600**, not 115200.

3. **Anomaly detection uses pattern analysis**, not just thresholds:
   - Oscillation: count motor sign-changes in 2s window
   - PID non-convergence: variance of distance/pid_error over 3s
   - Motor anti-correlation: Pearson correlation of left/right motors
   - Energy waste: average |motor_value| over time

4. **The Context Model graph maps signals to entities** so anomalies trace back to specific components in the graph.

5. **WebSocket disconnect must**: set `ws.onmessage = null` BEFORE `ws.close()`, then clear all signal/anomaly state.

6. **Import models via sys.path**: `sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'packages', 'shared-types', 'src'))`

7. **JSON fields in SQLite**: use `json.dumps()` on write, `json.loads()` on read.

8. **Backend logging**: print first 5 serial lines then go quiet. Always print anomalies and errors.

## Environment Variables

```
GEMINI_API_KEY — for Google Gemini API
ONSHAPE_ACCESS_KEY — for Onshape REST API
ONSHAPE_SECRET_KEY — for Onshape REST API
```

## Key Files

| File | Purpose |
|------|---------|
| `packages/shared-types/src/models.py` | All data models — the contract |
| `apps/backend/src/database.py` | SQLite schema |
| `apps/backend/src/context_engine.py` | Graph CRUD, impact analysis, snapshots |
| `apps/backend/src/connectors/` | GitHub, KiCad, Onshape parsers |
| `apps/backend/src/agent/solus_agent.py` | Gemini reasoning with graph context |
| `apps/backend/src/agent/memory_store.py` | TF-IDF semantic search |
| `apps/backend/src/live_bench.py` | Serial telemetry + smart anomaly detection |
| `apps/backend/src/simulator.py` | MuJoCo wrapper |
| `apps/backend/src/arduino_flasher.py` | Compile + upload via arduino-cli |
| `apps/backend/src/routes.py` | ALL API routes |
| `apps/backend/src/main.py` | FastAPI app entry |
| `apps/desktop/src/renderer/App.tsx` | 4-tab shell |
| `apps/desktop/src/renderer/stores/projectStore.ts` | Zustand state |
| `apps/desktop/src/renderer/components/` | Tab components |

## Style Guide

- **Frontend:** Dark theme, developer tool aesthetic (VS Code/Grafana). Use `solus-*` Tailwind colors from globals.css. Monospace for data. Compact. No rounded bubbly UI.
- **Backend:** Print statements for debugging, not logging framework. Keep it simple.

## Do NOT

- Do NOT hardcode demo responses — use real Gemini API
- Do NOT use synchronous serial reads in async functions
- Do NOT edit files you don't own (each agent has specific files)
- Do NOT install packages without checking requirements.txt first
