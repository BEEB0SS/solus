"""
MuJoCo simulator wrapper for diff-drive robot.
Falls back to simple kinematic stub when mujoco is not installed.

Backend owns ALL physics. Frontend (Three.js) only renders body positions
that this module computes.
"""

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
            "chassis_height": 0.03,
            "wheel_separation": 0.16,
            "motor_torque": 0.5,
            "kp": 2.0,
            "kd": 0.5,
            "target_distance": 0.25,
        }
        self.model = None
        self.data = None
        self._last_error = 0.0
        self._pid_running = False

        # Kinematic fallback state
        self._kin = {"x": 0.0, "y": 0.0, "z": 0.0, "theta": 0.0, "trail": [],
                     "left_motor": 0.0, "right_motor": 0.0, "distance": 100.0}

        # Body names to report to frontend
        self._body_names = ["chassis", "wheel_fl", "wheel_fr", "wheel_rl", "wheel_rr",
                            "obstacle_1", "obstacle_2", "obstacle_3", "obstacle_4"]
        # Obstacle sizes for frontend rendering
        self._obstacle_sizes = {
            "obstacle_1": [0.1, 0.15, 0.05],
            "obstacle_2": [0.075, 0.075, 0.05],
            "obstacle_3": [0.15, 0.05, 0.03],
            "obstacle_4": [0.05, 0.2, 0.05],
        }

    # ── MJCF Model ────────────────────────────────────────────────────

    def _build_mjcf(self) -> str:
        p = self.params
        wr = p["wheel_radius"]
        ww = p["wheel_width"]
        cl = p["chassis_length"]
        cw = p["chassis_width"]
        ch = p["chassis_height"]
        ws = p["wheel_separation"]
        torque = p["motor_torque"]

        return f"""
<mujoco model="elegoo_v4">
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <asset>
    <texture type="2d" name="grid" builtin="checker" width="512" height="512"
             rgb1="0.1 0.1 0.15" rgb2="0.15 0.15 0.2"/>
    <material name="grid_mat" texture="grid" texrepeat="8 8" reflectance="0.1"/>
    <material name="chassis_mat" rgba="0.2 0.2 0.8 1"/>
    <material name="wheel_mat" rgba="0.3 0.3 0.3 1"/>
    <material name="obstacle_mat" rgba="0.8 0.2 0.2 0.8"/>
    <material name="sensor_mat" rgba="0.2 0.8 0.2 1"/>
  </asset>
  <worldbody>
    <light pos="0 0 3" dir="0 0 -1" diffuse="0.8 0.8 0.8"/>
    <geom type="plane" size="2 2 0.01" material="grid_mat"/>

    <!-- Robot -->
    <body name="chassis" pos="0 0 {wr + ch/2 + 0.001:.4f}">
      <freejoint name="root"/>
      <geom type="box" size="{cl/2:.4f} {cw/2:.4f} {ch/2:.4f}" mass="0.5" material="chassis_mat"/>

      <!-- Front left wheel -->
      <body name="wheel_fl" pos="{cl/4:.4f} {ws/2:.4f} {-ch/2:.4f}">
        <joint name="motor_fl" type="hinge" axis="0 1 0" damping="0.01"/>
        <geom type="cylinder" size="{wr:.4f} {ww/2:.4f}" mass="0.05" material="wheel_mat"
              euler="90 0 0"/>
      </body>

      <!-- Front right wheel -->
      <body name="wheel_fr" pos="{cl/4:.4f} {-ws/2:.4f} {-ch/2:.4f}">
        <joint name="motor_fr" type="hinge" axis="0 1 0" damping="0.01"/>
        <geom type="cylinder" size="{wr:.4f} {ww/2:.4f}" mass="0.05" material="wheel_mat"
              euler="90 0 0"/>
      </body>

      <!-- Rear left wheel -->
      <body name="wheel_rl" pos="{-cl/4:.4f} {ws/2:.4f} {-ch/2:.4f}">
        <joint name="motor_rl" type="hinge" axis="0 1 0" damping="0.01"/>
        <geom type="cylinder" size="{wr:.4f} {ww/2:.4f}" mass="0.05" material="wheel_mat"
              euler="90 0 0"/>
      </body>

      <!-- Rear right wheel -->
      <body name="wheel_rr" pos="{-cl/4:.4f} {-ws/2:.4f} {-ch/2:.4f}">
        <joint name="motor_rr" type="hinge" axis="0 1 0" damping="0.01"/>
        <geom type="cylinder" size="{wr:.4f} {ww/2:.4f}" mass="0.05" material="wheel_mat"
              euler="90 0 0"/>
      </body>

      <!-- Ultrasonic sensor site (front center) -->
      <site name="ultrasonic" pos="{cl/2:.4f} 0 0" type="box" size="0.01 0.01 0.01"
            material="sensor_mat"/>
    </body>

    <!-- Obstacles -->
    <body name="obstacle_1" pos="0.5 0 0.05">
      <geom type="box" size="0.1 0.15 0.05" material="obstacle_mat"/>
    </body>
    <body name="obstacle_2" pos="-0.3 0.4 0.05">
      <geom type="box" size="0.075 0.075 0.05" material="obstacle_mat"/>
    </body>
    <body name="obstacle_3" pos="0.1 -0.5 0.03">
      <geom type="box" size="0.15 0.05 0.03" material="obstacle_mat"/>
    </body>
    <body name="obstacle_4" pos="-0.5 -0.3 0.05">
      <geom type="box" size="0.05 0.2 0.05" material="obstacle_mat"/>
    </body>
  </worldbody>

  <actuator>
    <motor joint="motor_fl" ctrlrange="-{torque} {torque}" name="left_front"/>
    <motor joint="motor_rl" ctrlrange="-{torque} {torque}" name="left_rear"/>
    <motor joint="motor_fr" ctrlrange="-{torque} {torque}" name="right_front"/>
    <motor joint="motor_rr" ctrlrange="-{torque} {torque}" name="right_rear"/>
  </actuator>

  <sensor>
    <rangefinder name="ultrasonic" site="ultrasonic"/>
    <velocimeter name="chassis_vel" site="ultrasonic"/>
  </sensor>
</mujoco>
"""

    # ── Model loading ─────────────────────────────────────────────────

    def load_from_params(self, params: dict):
        self.params.update(params)
        self._last_error = 0.0
        if self.available:
            try:
                xml = self._build_mjcf()
                self.model = mujoco.MjModel.from_xml_string(xml)
                self.data = mujoco.MjData(self.model)
                print("[simulator] MuJoCo model loaded")
            except Exception as e:
                print(f"[simulator] MuJoCo load failed: {e}")
                self.model = None
                self.data = None
        else:
            self.model = None
            self.data = None
            print("[simulator] kinematic stub (mujoco not available)")

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
            elif "chassis" in name or "body" in name or "frame" in name:
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

    # ── State readout ─────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Return ALL body positions/orientations for Three.js rendering."""
        torque = self.params.get("motor_torque", 0.5)

        if self.available and self.model is not None and self.data is not None:
            bodies = {}
            for name in self._body_names:
                try:
                    body_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, name)
                    if body_id < 0:
                        continue
                    pos = self.data.xpos[body_id].tolist()
                    quat = self.data.xquat[body_id].tolist()
                    entry = {"pos": [round(v, 5) for v in pos],
                             "quat": [round(v, 5) for v in quat]}
                    if name in self._obstacle_sizes:
                        entry["size"] = self._obstacle_sizes[name]
                    bodies[name] = entry
                except Exception:
                    continue

            # Read sensors
            distance_raw = -1.0
            try:
                sensor_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SENSOR, "ultrasonic")
                if sensor_id >= 0:
                    adr = self.model.sensor_adr[sensor_id]
                    distance_raw = float(self.data.sensordata[adr])
            except Exception:
                pass

            distance_cm = distance_raw * 100 if distance_raw >= 0 else 400.0

            sensors = {
                "distance_cm": round(distance_cm, 2),
                "left_motor": round(float(self.data.ctrl[0]) / torque, 4) if torque else 0,
                "right_motor": round(float(self.data.ctrl[2]) / torque, 4) if torque else 0,
                "pid_error": round(self._last_error, 4),
                "kp_value": self.params.get("kp", 2.0),
                "kd_value": self.params.get("kd", 0.5),
            }

            return {
                "bodies": bodies,
                "sensors": sensors,
                "time": round(float(self.data.time), 4),
                "mujoco": True,
            }

        # Kinematic fallback
        s = self._kin
        chassis_z = self.params["wheel_radius"] + self.params["chassis_height"] / 2
        bodies = {
            "chassis": {
                "pos": [round(s["x"], 5), round(s["y"], 5), round(chassis_z, 5)],
                "quat": self._euler_to_quat(0, 0, s["theta"]),
            },
        }
        # Approximate wheel positions
        cl = self.params["chassis_length"]
        ws = self.params["wheel_separation"]
        ch = self.params["chassis_height"]
        ct, st = math.cos(s["theta"]), math.sin(s["theta"])
        for wname, dx, dy in [("wheel_fl", cl/4, ws/2), ("wheel_fr", cl/4, -ws/2),
                               ("wheel_rl", -cl/4, ws/2), ("wheel_rr", -cl/4, -ws/2)]:
            wx = s["x"] + dx * ct - dy * st
            wy = s["y"] + dx * st + dy * ct
            bodies[wname] = {
                "pos": [round(wx, 5), round(wy, 5), round(self.params["wheel_radius"], 5)],
                "quat": self._euler_to_quat(0, 0, s["theta"]),
            }

        for oname, osize in self._obstacle_sizes.items():
            # Static obstacle positions from MJCF defaults
            opos = {"obstacle_1": [0.5, 0, 0.05], "obstacle_2": [-0.3, 0.4, 0.05],
                    "obstacle_3": [0.1, -0.5, 0.03], "obstacle_4": [-0.5, -0.3, 0.05]}
            bodies[oname] = {"pos": opos.get(oname, [0, 0, 0]), "quat": [1, 0, 0, 0], "size": osize}

        sensors = {
            "distance_cm": round(s["distance"], 2),
            "left_motor": round(s["left_motor"], 4),
            "right_motor": round(s["right_motor"], 4),
            "pid_error": round(self._last_error, 4),
            "kp_value": self.params.get("kp", 2.0),
            "kd_value": self.params.get("kd", 0.5),
        }

        return {
            "bodies": bodies,
            "sensors": sensors,
            "time": 0.0,
            "mujoco": False,
        }

    @staticmethod
    def _euler_to_quat(roll: float, pitch: float, yaw: float) -> list[float]:
        cr, sr = math.cos(roll / 2), math.sin(roll / 2)
        cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
        cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
        return [
            round(cr * cp * cy + sr * sp * sy, 5),
            round(sr * cp * cy - cr * sp * sy, 5),
            round(cr * sp * cy + sr * cp * sy, 5),
            round(cr * cp * sy - sr * sp * cy, 5),
        ]

    # ── Manual motor control ──────────────────────────────────────────

    def step_manual(self, left_motor: float, right_motor: float, n_steps: int = 50) -> dict:
        """Step simulation with manual motor inputs. Returns full state for Three.js."""
        torque = self.params.get("motor_torque", 0.5)

        if self.available and self.model is not None and self.data is not None:
            self.data.ctrl[0] = left_motor * torque   # left_front
            self.data.ctrl[1] = left_motor * torque    # left_rear
            self.data.ctrl[2] = right_motor * torque   # right_front
            self.data.ctrl[3] = right_motor * torque   # right_rear
            for _ in range(n_steps):
                mujoco.mj_step(self.model, self.data)
            return self.get_state()

        # Kinematic fallback
        s = self._kin
        dt = 0.002
        wr = self.params["wheel_radius"]
        ws = self.params.get("wheel_separation", 0.16)

        for _ in range(n_steps):
            v = wr * (left_motor + right_motor) / 2
            omega = wr * (right_motor - left_motor) / ws
            s["x"] += v * math.cos(s["theta"]) * dt
            s["y"] += v * math.sin(s["theta"]) * dt
            s["theta"] += omega * dt

        s["left_motor"] = left_motor
        s["right_motor"] = right_motor

        # Simple distance approximation to nearest obstacle
        min_dist = 400.0
        obs_positions = [[0.5, 0], [-0.3, 0.4], [0.1, -0.5], [-0.5, -0.3]]
        for ox, oy in obs_positions:
            d = math.sqrt((s["x"] - ox) ** 2 + (s["y"] - oy) ** 2) * 100
            min_dist = min(min_dist, d)
        s["distance"] = max(2.0, min_dist)

        s["trail"].append({"x": s["x"], "y": s["y"]})
        if len(s["trail"]) > 200:
            s["trail"] = s["trail"][-200:]

        return self.get_state()

    # ── PID step ──────────────────────────────────────────────────────

    def run_pid_step(self) -> dict:
        """Run one PID iteration: read sensor → compute control → step → return state."""
        kp = self.params.get("kp", 2.0)
        kd = self.params.get("kd", 0.5)
        target = self.params.get("target_distance", 0.25)
        torque = self.params.get("motor_torque", 0.5)
        base_speed = 0.3

        if self.available and self.model is not None and self.data is not None:
            # Read ultrasonic
            distance_raw = -1.0
            try:
                sensor_id = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SENSOR, "ultrasonic")
                if sensor_id >= 0:
                    adr = self.model.sensor_adr[sensor_id]
                    distance_raw = float(self.data.sensordata[adr])
            except Exception:
                pass

            distance_m = distance_raw if distance_raw >= 0 else 4.0

            error = distance_m - target
            derivative = error - self._last_error
            output = kp * error + kd * derivative
            self._last_error = error

            left = max(-1, min(1, base_speed + output))
            right = max(-1, min(1, base_speed - output))

            self.data.ctrl[0] = left * torque
            self.data.ctrl[1] = left * torque
            self.data.ctrl[2] = right * torque
            self.data.ctrl[3] = right * torque

            for _ in range(50):
                mujoco.mj_step(self.model, self.data)

            return self.get_state()

        # Kinematic fallback PID
        s = self._kin
        distance_m = s["distance"] / 100.0
        error = distance_m - target
        derivative = error - self._last_error
        output = kp * error + kd * derivative
        self._last_error = error

        left = max(-1, min(1, base_speed + output))
        right = max(-1, min(1, base_speed - output))

        return self.step_manual(left, right, n_steps=50)

    # ── Batch simulation run ──────────────────────────────────────────

    async def run_simulation(self, n_steps: int = 500, dt: float = 0.002,
                              kp: float = 2.0, target_dist: float = 0.25,
                              **extra_params) -> dict:
        """Run a full simulation batch, returns trajectory for plotting."""
        # Apply any extra params (wheel_radius, etc) if provided
        reload = False
        for k, v in extra_params.items():
            if k in self.params and self.params[k] != v:
                self.params[k] = v
                reload = True
        self.params["kp"] = kp
        self.params["target_distance"] = target_dist

        if reload and self.available:
            self.load_from_params(self.params)

        trajectory = []
        torque = self.params.get("motor_torque", 0.5)

        if self.available and self.model is not None and self.data is not None:
            mujoco.mj_resetData(self.model, self.data)
            self._last_error = 0.0

            for step in range(n_steps):
                state = self.run_pid_step()
                if step % 5 == 0:  # Sample every 5 steps
                    trajectory.append({
                        "t": round(float(self.data.time), 4),
                        "left_vel": state["sensors"]["left_motor"],
                        "right_vel": state["sensors"]["right_motor"],
                        "distance": state["sensors"]["distance_cm"],
                        "bodies": state["bodies"],
                    })
        else:
            # Kinematic stub
            self._kin = {"x": 0.0, "y": 0.0, "z": 0.0, "theta": 0.0,
                         "trail": [], "left_motor": 0.0, "right_motor": 0.0, "distance": 100.0}
            self._last_error = 0.0

            for step in range(n_steps):
                state = self.run_pid_step()
                if step % 5 == 0:
                    trajectory.append({
                        "t": round(step * dt, 4),
                        "left_vel": state["sensors"]["left_motor"],
                        "right_vel": state["sensors"]["right_motor"],
                        "distance": state["sensors"]["distance_cm"],
                        "bodies": state["bodies"],
                    })

        final = trajectory[-1] if trajectory else {}
        return {
            "trajectory": trajectory,
            "final_state": final,
            "params_used": dict(self.params),
        }

    # ── Reset ─────────────────────────────────────────────────────────

    def reset(self):
        self._last_error = 0.0
        self._pid_running = False
        self._kin = {"x": 0.0, "y": 0.0, "z": 0.0, "theta": 0.0,
                     "trail": [], "left_motor": 0.0, "right_motor": 0.0, "distance": 100.0}
        if self.available and self.model is not None and self.data is not None:
            mujoco.mj_resetData(self.model, self.data)
        return self.get_state()

    def reset_manual(self):
        return self.reset()

    # ── PID running state ─────────────────────────────────────────────

    def start_pid(self):
        self._pid_running = True

    def stop_pid(self):
        self._pid_running = False

    @property
    def pid_running(self):
        return self._pid_running

    # ── Comparison ────────────────────────────────────────────────────

    def compare_with_telemetry(self, sim_result: dict, live_state: dict) -> list[dict]:
        comparisons = []
        final = sim_result.get("final_state", {})
        final_sensors = final.get("sensors", final)
        signal_map = {
            "left_motor": "left_motor",
            "right_motor": "right_motor",
            "distance_cm": "distance_cm",
        }
        live_signals = live_state.get("signals", {})

        for sim_key, live_key in signal_map.items():
            sim_val = final_sensors.get(sim_key)
            if sim_val is None:
                # Try old format
                old_map = {"left_motor": "left_vel", "right_motor": "right_vel", "distance_cm": "distance"}
                sim_val = final.get(old_map.get(sim_key, sim_key))
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

    def load_from_onshape_stl(self, stl_data: bytes, part_name: str) -> str:
        import tempfile
        import os
        stl_path = os.path.join(tempfile.gettempdir(), f"solus_{part_name}.stl")
        with open(stl_path, 'wb') as f:
            f.write(stl_data)
        if not hasattr(self, '_mesh_paths'):
            self._mesh_paths = {}
        self._mesh_paths[part_name] = stl_path
        return stl_path
