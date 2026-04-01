"""
MuJoCo simulator wrapper for diff-drive robot.
Falls back to simple kinematic stub when mujoco is not installed.
"""

import asyncio
import math

try:
    import mujoco
    MUJOCO_AVAILABLE = True
except ImportError:
    MUJOCO_AVAILABLE = False


class MuJoCoSimulator:
    def __init__(self):
        self.available = MUJOCO_AVAILABLE
        self.params = {
            "wheel_radius": 0.033,
            "wheel_width": 0.026,
            "chassis_length": 0.20,
            "chassis_width": 0.15,
            "chassis_height": 0.05,
            "wheel_separation": 0.16,
            "motor_torque": 0.5,
        }
        self.model = None
        self.data = None

    def _build_mjcf(self, p: dict) -> str:
        wr = p["wheel_radius"]
        ww = p["wheel_width"]
        cl = p["chassis_length"]
        cw = p["chassis_width"]
        ch = p["chassis_height"]
        ws = p["wheel_separation"]
        mt = p["motor_torque"]
        cz = wr + ch / 2

        xml = f"""<mujoco model="diff_drive">
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <worldbody>
    <light diffuse=".5 .5 .5" pos="0 0 3" dir="0 0 -1"/>
    <geom type="plane" size="5 5 0.1" rgba="0.8 0.8 0.8 1"/>
    <body name="chassis" pos="0 0 {cz:.4f}">
      <joint type="free"/>
      <geom type="box" size="{cl/2:.4f} {cw/2:.4f} {ch/2:.4f}" mass="1.0" rgba="0.2 0.3 0.8 1"/>
      <site name="rangefinder" pos="{cl/2:.4f} 0 0" type="sphere" size="0.005"/>
      <body name="front_left_wheel" pos="{cl/4:.4f} {ws/2:.4f} {-ch/2:.4f}">
        <joint name="front_left" type="hinge" axis="0 1 0"/>
        <geom type="cylinder" size="{wr:.4f} {ww/2:.4f}" euler="90 0 0" mass="0.1" rgba="0.1 0.1 0.1 1"/>
      </body>
      <body name="front_right_wheel" pos="{cl/4:.4f} {-ws/2:.4f} {-ch/2:.4f}">
        <joint name="front_right" type="hinge" axis="0 1 0"/>
        <geom type="cylinder" size="{wr:.4f} {ww/2:.4f}" euler="90 0 0" mass="0.1" rgba="0.1 0.1 0.1 1"/>
      </body>
      <body name="rear_left_wheel" pos="{-cl/4:.4f} {ws/2:.4f} {-ch/2:.4f}">
        <joint name="rear_left" type="hinge" axis="0 1 0"/>
        <geom type="cylinder" size="{wr:.4f} {ww/2:.4f}" euler="90 0 0" mass="0.1" rgba="0.1 0.1 0.1 1"/>
      </body>
      <body name="rear_right_wheel" pos="{-cl/4:.4f} {-ws/2:.4f} {-ch/2:.4f}">
        <joint name="rear_right" type="hinge" axis="0 1 0"/>
        <geom type="cylinder" size="{wr:.4f} {ww/2:.4f}" euler="90 0 0" mass="0.1" rgba="0.1 0.1 0.1 1"/>
      </body>
    </body>
  </worldbody>
  <actuator>
    <motor joint="front_left" ctrlrange="-{mt} {mt}" name="left_motor"/>
    <motor joint="front_right" ctrlrange="-{mt} {mt}" name="right_motor"/>
    <motor joint="rear_left" ctrlrange="-{mt} {mt}" name="left_motor_rear"/>
    <motor joint="rear_right" ctrlrange="-{mt} {mt}" name="right_motor_rear"/>
  </actuator>
</mujoco>"""
        return xml

    def load_from_params(self, params: dict):
        self.params.update(params)
        xml = self._build_mjcf(self.params)
        if self.available:
            self.model = mujoco.MjModel.from_xml_string(xml)
            self.data = mujoco.MjData(self.model)
            print("[simulator] MuJoCo model loaded from params")
        else:
            self.model = None
            self.data = None
            print("[simulator] stored params for kinematic stub (mujoco not available)")

    def update_from_onshape(self, onshape_data: dict):
        parts = onshape_data.get("parts", [])
        params = dict(self.params)
        for part in parts:
            name = (part.get("name", "") or "").lower()
            dims = part.get("dimensions", {})
            if "wheel" in name:
                diameter = dims.get("diameter", dims.get("height", 0))
                if diameter > 0:
                    params["wheel_radius"] = diameter / 2
                width = dims.get("width", dims.get("thickness", 0))
                if width > 0:
                    params["wheel_width"] = width
            elif "chassis" in name:
                if "length" in dims:
                    params["chassis_length"] = dims["length"]
                if "width" in dims:
                    params["chassis_width"] = dims["width"]
                if "height" in dims:
                    params["chassis_height"] = dims["height"]
        self.load_from_params(params)

    def set_parameter(self, name: str, value: float):
        if name in self.params:
            self.params[name] = value
            self.load_from_params(self.params)

    async def run_simulation(self, n_steps: int = 500, dt: float = 0.002,
                              kp: float = 2.0, target_dist: float = 0.25) -> dict:
        trajectory = []

        if self.available and self.model and self.data:
            mujoco.mj_resetData(self.model, self.data)
            for step in range(n_steps):
                t = step * dt
                distance = max(0.05, 1.0 - t * 0.5 + 0.1 * math.sin(t * 3))
                error = distance - target_dist
                control = max(-1, min(1, kp * error))
                # Left pair
                self.data.ctrl[0] = control
                self.data.ctrl[2] = control
                # Right pair
                self.data.ctrl[1] = control
                self.data.ctrl[3] = control
                mujoco.mj_step(self.model, self.data)
                trajectory.append({
                    "t": round(t, 4),
                    "left_vel": round(float(self.data.ctrl[0]), 4),
                    "right_vel": round(float(self.data.ctrl[1]), 4),
                    "distance": round(distance, 4),
                })
        else:
            # Kinematic stub
            x, v = 1.0, 0.0
            for step in range(n_steps):
                t = step * dt
                distance = max(0.05, x)
                error = distance - target_dist
                control = max(-1, min(1, kp * error))
                v += control * dt * 5
                v *= 0.98  # damping
                x -= v * dt
                trajectory.append({
                    "t": round(t, 4),
                    "left_vel": round(control, 4),
                    "right_vel": round(control, 4),
                    "distance": round(distance, 4),
                })

        final = trajectory[-1] if trajectory else {}
        return {
            "trajectory": trajectory,
            "final_state": final,
            "params_used": dict(self.params),
        }

    def compare_with_telemetry(self, sim_result: dict, live_state: dict) -> list[dict]:
        comparisons = []
        final = sim_result.get("final_state", {})
        signal_map = {
            "left_vel": "left_motor",
            "right_vel": "right_motor",
            "distance": "distance_cm",
        }
        live_signals = live_state.get("signals", {})

        for sim_key, live_key in signal_map.items():
            sim_val = final.get(sim_key)
            live_info = live_signals.get(live_key)
            if sim_val is None or live_info is None:
                continue
            obs_val = live_info.get("value", 0) if isinstance(live_info, dict) else live_info
            delta = abs(sim_val - obs_val)
            denom = max(abs(sim_val), abs(obs_val), 1e-9)
            pct = delta / denom * 100

            if pct < 10:
                status = "match"
            elif pct < 30:
                status = "deviation"
            else:
                status = "mismatch"

            comparisons.append({
                "signal": live_key,
                "simulated": round(sim_val, 4),
                "observed": round(obs_val, 4),
                "delta": round(delta, 4),
                "pct_diff": round(pct, 1),
                "status": status,
            })

        return comparisons
