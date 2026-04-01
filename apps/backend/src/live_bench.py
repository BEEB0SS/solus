"""
Live Bench — serial telemetry ingestion + smart behavioral pattern analysis.
Connects to /dev/ttyUSB0 at 9600 baud (Elegoo V4 CH340 chip).
"""

import asyncio
import json
import math
import os
import random
import re
import sys
import time
from collections import deque
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'packages', 'shared-types', 'src'))
from models import RuntimeSignal, RuntimePacket, Anomaly, SignalStatus

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("[live_bench] pyserial not installed — serial features disabled")


class LiveBench:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.signal_history: dict[str, deque] = {}
        self.signal_thresholds: dict = {}
        self.anomalies: list = []
        self.listeners: list = []
        self.serial_connection = None
        self.running = False
        self._log_count = 0
        self._packet_count = 0
        self._analysis_interval = 10
        self._signal_entity_map: dict[str, list[str]] = {}

    # ── Pattern Analyzers ─────────────────────────────────────────────

    def _analyze_oscillation(self) -> list[Anomaly]:
        results = []
        for name in ("left_motor", "right_motor"):
            if name not in self.signal_history:
                continue
            values = list(self.signal_history[name])[-20:]
            if len(values) < 5:
                continue
            sign_changes = 0
            for i in range(1, len(values)):
                if abs(values[i]) < 0.05 or abs(values[i - 1]) < 0.05:
                    continue
                if (values[i] > 0) != (values[i - 1] > 0):
                    sign_changes += 1
            if sign_changes > 6:
                results.append(Anomaly(
                    project_id=self.project_id,
                    signal_name=name,
                    severity="warning",
                    description=f"Motor oscillation detected on {name}",
                    pattern_type="oscillation",
                    evidence=f"{sign_changes} direction reversals in 2 seconds",
                    expected="<2 reversals for stable PID",
                    affected_entity_ids=self._signal_entity_map.get(name, []),
                ))
        return results

    def _analyze_convergence(self) -> list[Anomaly]:
        results = []
        checks = {
            "pid_error": 5.0,
            "distance_cm": 50.0,
        }
        for name, threshold in checks.items():
            if name not in self.signal_history:
                continue
            values = list(self.signal_history[name])[-30:]
            if len(values) < 10:
                continue
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            if variance > threshold:
                results.append(Anomaly(
                    project_id=self.project_id,
                    signal_name=name,
                    severity="warning",
                    description=f"PID non-convergence on {name}",
                    pattern_type="non_convergence",
                    evidence=f"variance={variance:.1f}",
                    expected=f"<{threshold} after settling",
                    affected_entity_ids=self._signal_entity_map.get(name, []),
                ))
        return results

    def _analyze_correlation(self) -> list[Anomaly]:
        results = []
        if "left_motor" not in self.signal_history or "right_motor" not in self.signal_history:
            return results
        left = list(self.signal_history["left_motor"])[-20:]
        right = list(self.signal_history["right_motor"])[-20:]
        n = min(len(left), len(right))
        if n < 5:
            return results
        left = left[-n:]
        right = right[-n:]
        mean_l = sum(left) / n
        mean_r = sum(right) / n
        cov = sum((left[i] - mean_l) * (right[i] - mean_r) for i in range(n)) / n
        std_l = math.sqrt(sum((v - mean_l) ** 2 for v in left) / n)
        std_r = math.sqrt(sum((v - mean_r) ** 2 for v in right) / n)
        if std_l < 1e-9 or std_r < 1e-9:
            return results
        r = cov / (std_l * std_r)
        if r < -0.3:
            results.append(Anomaly(
                project_id=self.project_id,
                signal_name="left_motor,right_motor",
                severity="warning",
                description="Motor anti-correlation detected",
                pattern_type="anti_correlation",
                evidence=f"r={r:.2f}",
                expected=">0.5 for straight driving",
                affected_entity_ids=(
                    self._signal_entity_map.get("left_motor", []) +
                    self._signal_entity_map.get("right_motor", [])
                ),
            ))
        return results

    def _analyze_energy(self) -> list[Anomaly]:
        results = []
        motor_values = []
        for name in ("left_motor", "right_motor"):
            if name in self.signal_history:
                motor_values.extend(list(self.signal_history[name])[-20:])
        if len(motor_values) < 5:
            return results
        avg = sum(abs(v) for v in motor_values) / len(motor_values)
        if avg > 0.75:
            results.append(Anomaly(
                project_id=self.project_id,
                signal_name="left_motor,right_motor",
                severity="warning",
                description="Excessive motor energy usage",
                pattern_type="over_energy",
                evidence=f"{avg:.0%} utilization",
                expected="<40%",
                affected_entity_ids=(
                    self._signal_entity_map.get("left_motor", []) +
                    self._signal_entity_map.get("right_motor", [])
                ),
            ))
        return results

    def _get_affected_entities(self, signal_name: str) -> list[str]:
        return self._signal_entity_map.get(signal_name, [])

    def set_signal_entity_map(self, mapping: dict):
        self._signal_entity_map = mapping

    # ── Packet Ingestion ──────────────────────────────────────────────

    def ingest_packet(self, packet: dict) -> list[Anomaly]:
        signals = packet.get("signals", [])
        new_anomalies = []

        for sig in signals:
            name = sig.get("name", "")
            value = sig.get("value", 0.0)
            if name not in self.signal_history:
                self.signal_history[name] = deque(maxlen=200)
            self.signal_history[name].append(value)

            # Basic threshold check every packet
            if name in self.signal_thresholds:
                lo, hi = self.signal_thresholds[name]
                if value < lo or value > hi:
                    a = Anomaly(
                        project_id=self.project_id,
                        signal_name=name,
                        actual_value=value,
                        expected_range=(lo, hi),
                        severity="warning",
                        description=f"{name} out of range: {value}",
                        affected_entity_ids=self._signal_entity_map.get(name, []),
                    )
                    new_anomalies.append(a)

        self._packet_count += 1

        # Pattern analyzers every N packets
        pattern_anomalies = []
        if self._packet_count % self._analysis_interval == 0:
            pattern_anomalies.extend(self._analyze_oscillation())
            pattern_anomalies.extend(self._analyze_convergence())
            pattern_anomalies.extend(self._analyze_correlation())
            pattern_anomalies.extend(self._analyze_energy())
            new_anomalies.extend(pattern_anomalies)

        if new_anomalies:
            self.anomalies.extend(new_anomalies)
            for a in new_anomalies:
                print(f"[live_bench] ANOMALY: {a.pattern_type or 'threshold'} — {a.description}")

        # Broadcast to listeners
        msg = {
            "packet": packet,
            "anomalies": [asdict(a) for a in new_anomalies],
        }
        if pattern_anomalies:
            msg["anomaly_traces"] = [
                {
                    "pattern_type": a.pattern_type,
                    "signal_name": a.signal_name,
                    "evidence": a.evidence,
                    "expected": a.expected,
                    "affected_entity_ids": a.affected_entity_ids,
                }
                for a in pattern_anomalies
            ]
        self._broadcast(msg)

        return new_anomalies

    def _broadcast(self, msg: dict):
        for listener in self.listeners:
            try:
                listener(msg)
            except Exception:
                pass

    # ── Anomaly Report ────────────────────────────────────────────────

    def get_anomaly_report(self) -> dict:
        # Current signal values
        current_signals = {}
        for name, hist in self.signal_history.items():
            if hist:
                current_signals[name] = hist[-1]

        # Recent pattern anomalies
        pattern_anomalies = [a for a in self.anomalies if a.pattern_type]

        # Build text report
        lines = ["=== LIVE BENCH ANOMALY REPORT ===", ""]
        lines.append("CURRENT SIGNAL VALUES:")
        for name, val in current_signals.items():
            lines.append(f"  {name}: {val}")
        lines.append("")

        lines.append("PATTERN ANALYSIS:")
        if pattern_anomalies:
            for a in pattern_anomalies[-10:]:
                lines.append(f"  [{a.pattern_type}] {a.signal_name}: {a.evidence} (expected {a.expected})")
        else:
            lines.append("  No pattern anomalies detected.")
        lines.append("")

        lines.append("RAW DATA SNAPSHOT:")
        for name, hist in self.signal_history.items():
            vals = list(hist)[-5:]
            lines.append(f"  {name}: {vals}")

        report_text = "\n".join(lines)

        return {
            "signals": current_signals,
            "anomalies": [asdict(a) for a in self.anomalies[-20:]],
            "pattern_anomalies": [asdict(a) for a in pattern_anomalies[-10:]],
            "report": report_text,
            "signal_count": len(current_signals),
            "anomaly_count": len(self.anomalies),
        }

    # ── Serial Connection ─────────────────────────────────────────────

    async def start_serial(self, port: str = "", baud: int = 9600):
        if not SERIAL_AVAILABLE:
            print("[live_bench] pyserial not available")
            return

        # Auto-detect port if not specified
        if not port:
            detected = self.list_serial_ports()
            for p in detected:
                if p.get("is_arduino"):
                    port = p["device"]
                    break
            if not port and detected:
                port = detected[0]["device"]
            if not port:
                print("[live_bench] no serial port detected")
                return
            print(f"[live_bench] auto-detected port: {port}")

        self.running = True
        loop = asyncio.get_event_loop()

        try:
            self.serial_connection = serial.Serial(port, baud, timeout=1)
            print(f"[live_bench] opened {port} at {baud} baud")
        except Exception as e:
            print(f"[live_bench] serial open failed: {e}")
            self.running = False
            return

        # Arduino resets on serial open — wait for boot
        await asyncio.sleep(3)
        # Drain CH340 buffer fully — reset_input_buffer() misses the USB chip buffer on macOS
        self.serial_connection.timeout = 0.1
        while self.serial_connection.read(4096):
            pass
        self.serial_connection.timeout = 1
        print("[live_bench] serial buffer drained")

        while self.running:
            try:
                raw = await loop.run_in_executor(None, self.serial_connection.readline)
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                self._log_count += 1
                if self._log_count <= 5:
                    print(f"[live_bench] serial: {line}")

                packet = self._parse_line(line)
                if packet:
                    self.ingest_packet(packet)

            except Exception as e:
                if self.running:
                    print(f"[live_bench] serial error: {e}")
                break

    def _parse_line(self, line: str) -> dict | None:
        # Try JSON first
        try:
            data = json.loads(line)
            if "signals" in data:
                return data
            # Single-object signal
            if "name" in data and "value" in data:
                return {"signals": [data]}
        except (json.JSONDecodeError, ValueError):
            pass

        # Try "Word: Number unit" format
        match = re.match(r'^(\w+):\s*([-\d.]+)\s*(\w*)$', line)
        if match:
            return {
                "signals": [{
                    "name": match.group(1).lower(),
                    "value": float(match.group(2)),
                    "unit": match.group(3),
                }]
            }

        # Try CSV "key=val" format
        if "=" in line:
            signals = []
            for part in line.split(","):
                part = part.strip()
                kv = part.split("=", 1)
                if len(kv) == 2:
                    try:
                        signals.append({
                            "name": kv[0].strip().lower(),
                            "value": float(kv[1].strip()),
                            "unit": "",
                        })
                    except ValueError:
                        continue
            if signals:
                return {"signals": signals}

        return None

    # ── Simulated Telemetry ───────────────────────────────────────────

    async def start_simulated(self, interval: float = 0.1):
        self.running = True
        t0 = time.time()
        print("[live_bench] starting simulated telemetry")

        while self.running:
            t = time.time() - t0
            left = 0.5 + 0.3 * math.sin(t * 0.5) + random.gauss(0, 0.02)
            right = 0.5 + 0.3 * math.cos(t * 0.5) + random.gauss(0, 0.02)
            dist = max(5, 50 + 30 * math.sin(t * 0.2) + random.gauss(0, 2))
            battery = 12.6 - t * 0.001
            imu_roll = random.gauss(0, 2)
            imu_pitch = random.gauss(0, 2)
            temp = 25 + t * 0.01

            # 2% spike chance
            if random.random() < 0.02:
                left = random.choice([-1.0, 1.0])
                right = -left

            packet = {
                "signals": [
                    {"name": "left_motor", "value": round(left, 3), "unit": "duty"},
                    {"name": "right_motor", "value": round(right, 3), "unit": "duty"},
                    {"name": "distance_cm", "value": round(dist, 1), "unit": "cm"},
                    {"name": "battery_v", "value": round(battery, 2), "unit": "V"},
                    {"name": "imu_roll", "value": round(imu_roll, 2), "unit": "deg"},
                    {"name": "imu_pitch", "value": round(imu_pitch, 2), "unit": "deg"},
                    {"name": "temp_c", "value": round(temp, 1), "unit": "C"},
                ],
            }
            self.ingest_packet(packet)
            await asyncio.sleep(interval)

    # ── Serial Command ────────────────────────────────────────────────

    def send_serial_command(self, cmd: str):
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.write((cmd + "\n").encode("utf-8"))
            print(f"[live_bench] sent: {cmd}")
        else:
            print("[live_bench] no serial connection open")

    # ── Stop / State ──────────────────────────────────────────────────

    def stop(self):
        self.running = False
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            self.serial_connection = None
        self.signal_history.clear()
        self.anomalies.clear()
        self._packet_count = 0
        self._log_count = 0
        self._broadcast({"event": "disconnected"})
        print("[live_bench] stopped")

    def get_current_state(self) -> dict:
        current = {}
        for name, hist in self.signal_history.items():
            if hist:
                current[name] = {
                    "value": hist[-1],
                    "min": min(hist),
                    "max": max(hist),
                    "count": len(hist),
                }
        return {
            "running": self.running,
            "signals": current,
            "anomaly_count": len(self.anomalies),
            "packet_count": self._packet_count,
        }

    def get_recent_anomalies(self, limit: int = 20) -> list[dict]:
        return [asdict(a) for a in self.anomalies[-limit:]]

    @staticmethod
    def list_serial_ports() -> list[dict]:
        if not SERIAL_AVAILABLE:
            return []
        all_ports = serial.tools.list_ports.comports()
        print(f"[ports] found: {[p.device for p in all_ports]}")
        ports = []
        for p in all_ports:
            desc = (p.description or "").lower()
            dev = (p.device or "").lower()
            # Only skip Bluetooth ports
            if "bluetooth" in desc or "bluetooth" in dev:
                continue
            is_arduino = (
                p.vid == 0x1A86 or          # CH340
                p.vid == 0x2341 or          # Official Arduino
                "usb" in dev or
                "serial" in desc
            )
            ports.append({
                "device": p.device,
                "description": p.description,
                "hwid": p.hwid,
                "vid": p.vid,
                "pid": p.pid,
                "is_arduino": is_arduino,
            })
        # Arduino-flagged ports first, then alphabetical
        ports.sort(key=lambda x: (not x["is_arduino"], x["device"]))
        return ports
