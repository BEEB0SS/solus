"""
End-to-end demo flow test.
Requires the server to be running on port 8000.

Usage:
    cd apps/backend && python3 tests/test_demo_flow.py
"""

import requests
import time
import json
import sys

BASE = "http://127.0.0.1:8000"

passed = 0
failed = 0


def test(name, fn):
    global passed, failed
    try:
        result = fn()
        print(f"  \u2713 {name}")
        passed += 1
        return result
    except Exception as e:
        print(f"  \u2717 {name}: {e}")
        failed += 1
        return None


print("=== DEMO FLOW TESTS ===\n")


# 1. Health
def t_health():
    r = requests.get(f"{BASE}/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

test("Health check", t_health)


# 2. Create project
def t_create_project():
    # cleanup (may 404/405 — that's fine)
    try:
        requests.delete(f"{BASE}/api/projects/test-demo")
    except Exception:
        pass
    r = requests.post(f"{BASE}/api/projects", json={
        "name": "Test Robot", "id": "test-demo",
        "description": "Build obstacle avoidance",
    })
    assert r.status_code == 200
    assert r.json()["id"] == "test-demo"

test("Create project", t_create_project)


# 3. Add team
def t_add_team():
    r = requests.post(f"{BASE}/api/projects/test-demo/team", json={
        "name": "Tester", "role": "Software",
    })
    assert r.status_code == 200

test("Add team member", t_add_team)


# 4. Add KiCad source
kid = None

def t_add_kicad():
    global kid
    r = requests.post(f"{BASE}/api/projects/test-demo/sources", json={
        "source_type": "kicad", "name": "PCB",
        "config": {"path": "demo-assets/elegoo_kicad"},
    })
    assert r.status_code == 200
    kid = r.json()["id"]
    return kid

test("Add KiCad source", t_add_kicad)


# 5. Sync KiCad
def t_sync_kicad():
    assert kid is not None, "No KiCad source ID"
    r = requests.post(f"{BASE}/api/projects/test-demo/sources/{kid}/sync")
    assert r.status_code == 200
    d = r.json()
    print(f"    Entities: {d.get('entities_created', 0)}, Relations linked: {d.get('relations_linked', 0)}")
    assert d.get("entities_created", 0) > 0 or d.get("entities_updated", 0) > 0

test("Sync KiCad", t_sync_kicad)


# 6. Add GitHub source
gid = None

def t_add_github():
    global gid
    r = requests.post(f"{BASE}/api/projects/test-demo/sources", json={
        "source_type": "github", "name": "Code",
        "config": {"path": "demo-assets/robot-code"},
    })
    assert r.status_code == 200
    gid = r.json()["id"]
    return gid

test("Add GitHub source", t_add_github)


# 7. Sync GitHub
def t_sync_github():
    assert gid is not None, "No GitHub source ID"
    r = requests.post(f"{BASE}/api/projects/test-demo/sources/{gid}/sync")
    assert r.status_code == 200

test("Sync GitHub", t_sync_github)


# 8. Check graph
def t_graph():
    r = requests.get(f"{BASE}/api/projects/test-demo/graph")
    assert r.status_code == 200
    d = r.json()
    print(f"    Entities: {len(d['entities'])}, Relations: {len(d['relations'])}")
    assert len(d["entities"]) >= 10
    assert len(d["relations"]) >= 3

test("Graph has connected nodes", t_graph)


# 9. Agent query
def t_agent():
    r = requests.post(f"{BASE}/api/projects/test-demo/agent/query", json={
        "query": "What motor driver does this robot use?",
        "query_type": "general",
    })
    assert r.status_code == 200
    d = r.json()
    txt = str(d.get("response_text", ""))
    print(f"    Response: {txt[:80]}...")
    assert len(txt) > 20

test("Agent responds", t_agent)


# 10. Start simulated telemetry
def t_start_bench():
    r = requests.post(f"{BASE}/api/projects/test-demo/live-bench/start", json={
        "mode": "simulated",
    })
    assert r.status_code == 200

test("Start simulated live bench", t_start_bench)

time.sleep(3)


# 11. Check signals
def t_signals():
    r = requests.get(f"{BASE}/api/projects/test-demo/live-bench/state")
    assert r.status_code == 200
    d = r.json()
    sigs = d.get("signals", {})
    print(f"    Signals: {len(sigs)}")
    assert len(sigs) >= 4

test("Signals streaming", t_signals)


# 12. Device discovery
def t_discovery():
    r = requests.post(f"{BASE}/api/projects/test-demo/live-bench/discover")
    assert r.status_code == 200
    d = r.json()
    print(f"    Discovered: {d.get('discovered_peripherals', [])}")

test("Device discovery", t_discovery)


# 13. Get anomaly report
def t_anomaly_report():
    r = requests.get(f"{BASE}/api/projects/test-demo/live-bench/logs")
    assert r.status_code == 200
    d = r.json()
    print(f"    Report length: {len(d.get('report', ''))} chars")

test("Anomaly report", t_anomaly_report)


# 14. Simulator manual control
def t_sim_manual():
    r = requests.post(f"{BASE}/api/projects/test-demo/simulator/manual", json={
        "command": "FORWARD",
    })
    print(f"    Status: {r.status_code}, Response: {r.text[:100]}")

test("Simulator manual control", t_sim_manual)


# 15. Stop
def t_stop_bench():
    r = requests.post(f"{BASE}/api/projects/test-demo/live-bench/stop")
    assert r.status_code == 200

test("Stop live bench", t_stop_bench)


# 16. Serial ports
def t_serial_ports():
    r = requests.get(f"{BASE}/api/serial-ports")
    assert r.status_code == 200
    ports = r.json()
    arduino = [p for p in ports if p.get("is_arduino")]
    print(f"    Ports: {len(ports)}, Arduino: {len(arduino)}")

test("Serial ports", t_serial_ports)


# 17. Impact analysis
def t_impact():
    r = requests.get(f"{BASE}/api/projects/test-demo/graph")
    entities = r.json()["entities"]
    motor_driver = [e for e in entities if "TB6612" in e.get("name", "")]
    if motor_driver:
        r2 = requests.get(f"{BASE}/api/projects/test-demo/impact/{motor_driver[0]['id']}")
        print(f"    Impacted: {r2.json().get('total_impacted', 0)} entities")
    else:
        print("    (no TB6612 entity found, skipping impact check)")

test("Impact analysis", t_impact)


# 18. Activity
def t_activity():
    r = requests.get(f"{BASE}/api/projects/test-demo/activity")
    assert r.status_code == 200
    print(f"    Activities: {len(r.json())}")

test("Activity feed", t_activity)


print(f"\n=== DONE === {passed} passed, {failed} failed")
if failed > 0:
    sys.exit(1)
