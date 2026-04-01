"""
Cross-domain linker and device discovery.

CrossDomainLinker — discovers relationships between entities from different
domains (code, electronics, mechanical) by analyzing their actual content.

DeviceDiscovery — analyzes live telemetry signal names and value ranges to
auto-discover connected peripherals and build graph entities.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'packages', 'shared-types', 'src'))
from models import Entity, Relation, EntityType, RelationType, SourceType


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CrossDomainLinker
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CrossDomainLinker:
    def __init__(self, context_engine):
        self.ce = context_engine

    def link_project(self, project_id: str) -> dict:
        """Run all linkers and return summary of relations created."""
        entities = self.ce.get_entities_by_project(project_id)
        return {
            "code_to_electrical": self._link_code_to_electrical(project_id, entities),
            "electrical_to_mechanical": self._link_electrical_to_mechanical(project_id, entities),
            "enriched": self._auto_enrich_descriptions(project_id, entities),
        }

    # ── Code → Electrical ─────────────────────────────────────────────

    def _link_code_to_electrical(self, project_id, entities):
        """
        Parse Arduino/C++ code for pin definitions and match to KiCad
        nets / electrical components.  NOT hardcoded — reads real code.
        """
        relations_created = 0

        code_entities = [e for e in entities if e.entity_type.value == "software_module"]
        electrical_entities = [e for e in entities if e.entity_type.value == "electrical_part"]
        interface_entities = [e for e in entities if e.entity_type.value == "interface"]

        for code_ent in code_entities:
            content = code_ent.metadata.get("file_content", "")
            if not content:
                continue

            # 1-2. Extract #define PIN mappings
            defines = re.findall(r'#define\s+(\w+)\s+(\d+)', content)
            pin_map = {name: int(num) for name, num in defines}

            # 3. Extract direct pin usage
            pin_writes = re.findall(r'(?:analogWrite|digitalWrite)\s*\(\s*(\w+)', content)
            pin_reads = re.findall(r'(?:digitalRead|analogRead|pulseIn)\s*\(\s*(\w+)', content)

            # 5. Resolve names → numbers
            write_pins: set[int] = set()
            read_pins: set[int] = set()
            for p in pin_writes:
                if p in pin_map:
                    write_pins.add(pin_map[p])
                elif p.isdigit():
                    write_pins.add(int(p))
            for p in pin_reads:
                if p in pin_map:
                    read_pins.add(pin_map[p])
                elif p.isdigit():
                    read_pins.add(int(p))

            # 6-8. Match define names against KiCad interface (net) names
            for iface in interface_entities:
                iface_name_upper = iface.name.upper()
                iface_rels = self.ce.get_relations_for_entity(iface.id)
                connected_parts = []
                for rel in iface_rels:
                    other_id = (rel.target_entity_id
                                if rel.source_entity_id == iface.id
                                else rel.source_entity_id)
                    other = self.ce.get_entity(other_id)
                    if other and other.entity_type.value == "electrical_part":
                        connected_parts.append(other)

                for define_name, pin_num in pin_map.items():
                    if (define_name.upper() in iface_name_upper
                            or iface_name_upper in define_name.upper()):
                        rel_type = "drives" if pin_num in write_pins else "reads_from"
                        for comp in connected_parts:
                            if comp.id == code_ent.id:
                                continue
                            if self._relation_exists(code_ent.id, comp.id, rel_type):
                                continue
                            self.ce.create_relation(Relation(
                                project_id=project_id,
                                source_entity_id=code_ent.id,
                                target_entity_id=comp.id,
                                relation_type=RelationType(rel_type),
                                metadata={"via_pin": pin_num, "via_net": iface.name,
                                          "define": define_name},
                                confidence=0.9,
                            ))
                            relations_created += 1

            # 9. Library-based linking — Servo
            if re.search(r'\bServo\b', content):
                for comp in electrical_entities:
                    cn = comp.name.upper()
                    if "SERVO" in cn or "SG90" in cn or "MG90" in cn or "MG995" in cn:
                        if not self._relation_exists(code_ent.id, comp.id):
                            self.ce.create_relation(Relation(
                                project_id=project_id,
                                source_entity_id=code_ent.id,
                                target_entity_id=comp.id,
                                relation_type=RelationType.DRIVES,
                                metadata={"via": "servo_library"},
                                confidence=0.8,
                            ))
                            relations_created += 1

            # 9. Library-based linking — Serial / wireless
            if "Serial.begin" in content or "Serial.print" in content:
                for comp in electrical_entities:
                    cn = comp.name.upper()
                    if any(kw in cn for kw in ("ESP32", "BLUETOOTH", "HC-05", "HC-06",
                                                "WIFI", "XBEE", "NRF24", "LORA")):
                        if not self._relation_exists(code_ent.id, comp.id):
                            self.ce.create_relation(Relation(
                                project_id=project_id,
                                source_entity_id=code_ent.id,
                                target_entity_id=comp.id,
                                relation_type=RelationType.CONNECTED_TO,
                                metadata={"via": "serial"},
                                confidence=0.7,
                            ))
                            relations_created += 1

            # 9. Library-based linking — Wire / I2C
            if re.search(r'#include\s*[<"]Wire\.h[">]', content) or "Wire.begin" in content:
                for comp in electrical_entities:
                    cn = comp.name.upper()
                    if any(kw in cn for kw in ("MPU", "BMP", "BME", "ADS", "OLED",
                                                "SSD1306", "INA219", "PCA9685")):
                        if not self._relation_exists(code_ent.id, comp.id):
                            self.ce.create_relation(Relation(
                                project_id=project_id,
                                source_entity_id=code_ent.id,
                                target_entity_id=comp.id,
                                relation_type=RelationType.CONNECTED_TO,
                                metadata={"via": "i2c"},
                                confidence=0.7,
                            ))
                            relations_created += 1

        return {"relations_created": relations_created}

    # ── Electrical → Mechanical ───────────────────────────────────────

    def _link_electrical_to_mechanical(self, project_id, entities):
        """Link electrical components to mechanical parts by general name heuristics."""
        relations_created = 0
        electrical = [e for e in entities if e.entity_type.value == "electrical_part"]
        mechanical = [e for e in entities if e.entity_type.value == "mechanical_part"]

        for elec in electrical:
            en = elec.name.upper()
            for mech in mechanical:
                mn = mech.name.upper()
                should_link = False
                rel_type = "connected_to"

                # Motor / motor driver → wheel
                if any(kw in en for kw in ("MOTOR", "TB6612", "L298", "L293", "DRV8833")):
                    if "WHEEL" in mn:
                        should_link = True
                        rel_type = "drives"
                # Sensor / ultrasonic → mount / bracket
                if any(kw in en for kw in ("SENSOR", "ULTRASONIC", "HC-SR04",
                                            "IR", "LIDAR", "TOF")):
                    if any(kw in mn for kw in ("MOUNT", "BRACKET", "HOLDER")):
                        should_link = True
                # Servo → mount / bracket
                if any(kw in en for kw in ("SERVO", "SG90", "MG90", "MG995")):
                    if any(kw in mn for kw in ("MOUNT", "BRACKET", "HOLDER", "ARM")):
                        should_link = True
                # Camera → mount
                if any(kw in en for kw in ("CAMERA", "ESP32-CAM", "OV2640")):
                    if any(kw in mn for kw in ("MOUNT", "BRACKET", "HOLDER")):
                        should_link = True

                if should_link and not self._relation_exists(elec.id, mech.id):
                    self.ce.create_relation(Relation(
                        project_id=project_id,
                        source_entity_id=elec.id,
                        target_entity_id=mech.id,
                        relation_type=RelationType(rel_type),
                        metadata={"auto_linked": True},
                        confidence=0.7,
                    ))
                    relations_created += 1

        return {"relations_created": relations_created}

    # ── Auto-enrich descriptions ──────────────────────────────────────

    def _auto_enrich_descriptions(self, project_id, entities):
        """Generate descriptions from metadata + graph connections for entities that lack one."""
        enriched = 0
        for e in entities:
            if e.description and len(e.description) > 20:
                continue

            etype = e.entity_type.value
            meta = e.metadata if isinstance(e.metadata, dict) else {}
            parts: list[str] = []

            if etype == "electrical_part":
                parts = self._describe_electrical(e, meta)
            elif etype == "software_module":
                parts = self._describe_software(e, meta)
            elif etype == "mechanical_part":
                parts = self._describe_mechanical(e, meta)

            # Append connection info for ALL types
            connected = self._get_connected_names(e.id)
            if connected:
                parts.append(f"Connected to: {', '.join(connected)}")

            if parts:
                self.ce.update_entity(e.id, {"description": ". ".join(parts) + "."})
                enriched += 1

        return {"enriched": enriched}

    # ── Description helpers ───────────────────────────────────────────

    def _describe_electrical(self, entity, meta) -> list[str]:
        parts: list[str] = []
        category = meta.get("component_category", "")
        value = meta.get("value", "")

        cat_descriptions = {
            "motor_driver": (f"Motor driver IC ({value})", "Converts PWM signals to motor outputs"),
            "microcontroller": (f"Microcontroller ({value})", "Main processing unit running firmware"),
            "ultrasonic_sensor": ("Ultrasonic distance sensor", "Measures distance via echo timing, range 2-400cm"),
            "wireless_module": ("WiFi/camera module", "Provides wireless connectivity and/or video streaming"),
            "voltage_regulator": (f"Voltage regulator ({value})",),
            "resistor": (f"Resistor {value}",),
            "capacitor": (f"Capacitor {value}",),
        }
        if category in cat_descriptions:
            parts.extend(cat_descriptions[category])
        elif "HC-SR04" in (value or ""):
            parts.extend(("Ultrasonic distance sensor", "Measures distance via echo timing, range 2-400cm"))
        elif "ESP32" in (value or ""):
            parts.extend(("WiFi/camera module", "Provides wireless connectivity and/or video streaming"))
        elif "motor" in entity.name.lower():
            parts.extend(("DC gear motor", "Drives wheel via motor driver"))
        elif "servo" in entity.name.lower():
            parts.extend(("Micro servo motor", "Rotates sensor head for scanning"))
        return parts

    def _describe_software(self, entity, meta) -> list[str]:
        parts: list[str] = []
        content = meta.get("file_content", "")
        if not content:
            return parts
        if "PID" in content or "pid" in content:
            parts.append("PID controller firmware")
        if re.search(r'obstacle|avoidance', content, re.IGNORECASE):
            parts.append("Implements obstacle avoidance")
        if "Serial.begin" in content:
            parts.append("Streams telemetry over serial")
        defines = re.findall(r'#define\s+(\w+)\s+(\d+)', content)
        if defines:
            pin_list = ", ".join(f"{n}={v}" for n, v in defines[:6])
            parts.append(f"Pin mappings: {pin_list}")
        return parts

    def _describe_mechanical(self, entity, meta) -> list[str]:
        parts: list[str] = []
        name = entity.name.lower()
        if "wheel" in name:
            d = meta.get("diameter_mm", meta.get("diameter", ""))
            parts.append("Drive wheel" + (f" ({d}mm)" if d else ""))
        elif "chassis" in name:
            parts.append("Main structural frame")
        elif "mount" in name or "bracket" in name:
            parts.append("Mounting bracket for sensor/component")
        return parts

    def _get_connected_names(self, entity_id: str, limit: int = 5) -> list[str]:
        names: list[str] = []
        for r in self.ce.get_relations_for_entity(entity_id)[:limit]:
            other_id = r.target_entity_id if r.source_entity_id == entity_id else r.source_entity_id
            other = self.ce.get_entity(other_id)
            if other:
                names.append(other.name)
        return names

    # ── Helpers ───────────────────────────────────────────────────────

    def _relation_exists(self, source_id: str, target_id: str,
                         rel_type: str = None) -> bool:
        for r in self.ce.get_relations_for_entity(source_id):
            if r.target_entity_id == target_id:
                if rel_type is None or r.relation_type.value == rel_type:
                    return True
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DeviceDiscovery
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeviceDiscovery:
    """
    Analyzes live telemetry signal names + value ranges to auto-discover
    connected peripherals and build graph entities.

    Works with ANY Arduino/microcontroller streaming named signals.
    """

    # General signal classification — not robot-specific
    SENSOR_PATTERNS: dict[str, dict] = {
        "distance":  {"category": "ultrasonic_sensor", "component": "Ultrasonic Distance Sensor"},
        "sonar":     {"category": "ultrasonic_sensor", "component": "Ultrasonic Distance Sensor"},
        "ir":        {"category": "ir_sensor",         "component": "IR Sensor"},
        "line":      {"category": "line_sensor",       "component": "Line Tracking Sensor"},
        "motor":     {"category": "motor_output",      "component": "DC Motor"},
        "servo":     {"category": "servo",             "component": "Servo Motor"},
        "temp":      {"category": "temperature_sensor","component": "Temperature Sensor"},
        "humidity":  {"category": "humidity_sensor",   "component": "Humidity Sensor"},
        "imu":       {"category": "imu",               "component": "IMU Sensor"},
        "gyro":      {"category": "imu",               "component": "Gyroscope"},
        "accel":     {"category": "imu",               "component": "Accelerometer"},
        "battery":   {"category": "power_monitor",     "component": "Battery Monitor"},
        "voltage":   {"category": "power_monitor",     "component": "Voltage Monitor"},
        "current":   {"category": "power_monitor",     "component": "Current Monitor"},
        "encoder":   {"category": "encoder",           "component": "Rotary Encoder"},
        "rpm":       {"category": "encoder",           "component": "Rotary Encoder"},
        "pid":       {"category": "control_param",     "component": None},
        "kp":        {"category": "control_param",     "component": None},
        "kd":        {"category": "control_param",     "component": None},
        "ki":        {"category": "control_param",     "component": None},
        "running":   {"category": "system_state",      "component": None},
        "bug":       {"category": "system_state",      "component": None},
        "camera":    {"category": "camera",            "component": "Camera Module"},
        "lidar":     {"category": "lidar",             "component": "LiDAR Sensor"},
        "pressure":  {"category": "pressure_sensor",   "component": "Pressure Sensor"},
        "light":     {"category": "light_sensor",      "component": "Light Sensor"},
        "lux":       {"category": "light_sensor",      "component": "Light Sensor"},
        "compass":   {"category": "compass",           "component": "Magnetometer"},
        "heading":   {"category": "compass",           "component": "Magnetometer"},
        "gps":       {"category": "gps",               "component": "GPS Module"},
        "lat":       {"category": "gps",               "component": "GPS Module"},
        "lon":       {"category": "gps",               "component": "GPS Module"},
    }

    # VID → MCU type mapping
    MCU_VID_MAP: dict[int, str] = {
        0x1A86: "Arduino Uno (CH340)",        # CH340 — common clone
        0x2341: "Arduino (Official)",          # Arduino official
        0x10C4: "Arduino (CP2102)",            # Silicon Labs CP2102
        0x0403: "Arduino (FTDI)",              # FTDI chip
        0x239A: "Adafruit Board",
        0x303A: "ESP32 (Espressif)",
        0x1B4F: "SparkFun Board",
        0x2E8A: "Raspberry Pi Pico",
    }

    def __init__(self, context_engine):
        self.ce = context_engine

    def discover_from_telemetry(self, project_id: str, signals: dict,
                                 port_info: dict = None) -> dict:
        """
        Analyze telemetry signals and port info to discover peripherals.

        Args:
            project_id: project to add entities to
            signals: from LiveBench.get_current_state()["signals"]
                     e.g. {"distance_cm": {"value": 54, "min": 2, "max": 100, "count": 50}}
            port_info: from serial port detection
                     e.g. {"device": "/dev/cu.usbserial-2130", "vid": 6790, ...}
        """
        entities_created = 0
        relations_created = 0
        discovered: list[str] = []

        # 1. Create / find MCU entity
        mcu_name = self._detect_mcu(port_info)
        mcu_entity = self._find_or_create_entity(
            project_id=project_id,
            entity_type=EntityType.ELECTRICAL_PART,
            name=mcu_name,
            source_ref=f"runtime:mcu:{port_info.get('device', 'unknown') if port_info else 'unknown'}",
            metadata={
                "component_category": "microcontroller",
                "discovered_from": "telemetry",
                **({"vid": port_info.get("vid"), "pid": port_info.get("pid"),
                    "port": port_info.get("device")} if port_info else {}),
            },
        )
        if mcu_entity["created"]:
            entities_created += 1

        # 2-3. Classify signals and group by category
        grouped: dict[str, list[tuple[str, dict, dict]]] = {}
        for sig_name, sig_data in signals.items():
            classification = self._classify_signal(sig_name, sig_data)
            cat = classification["category"]
            grouped.setdefault(cat, []).append((sig_name, sig_data, classification))

        # 4-5. Create entities per group
        for cat, items in grouped.items():
            component_type = items[0][2].get("component")
            if not component_type:
                continue  # skip control_param, system_state etc.

            if cat == "motor_output":
                # Create SEPARATE entity per motor signal
                for sig_name, sig_data, cls in items:
                    label = self._signal_to_label(sig_name)
                    periph_name = f"{label} {component_type}"
                    result = self._find_or_create_entity(
                        project_id=project_id,
                        entity_type=EntityType.ELECTRICAL_PART,
                        name=periph_name,
                        source_ref=f"runtime:peripheral:{sig_name}",
                        metadata={
                            "component_category": cat,
                            "discovered_from": "telemetry",
                            "signals": [sig_name],
                            "value_range": {"min": sig_data.get("min"), "max": sig_data.get("max")},
                        },
                    )
                    if result["created"]:
                        entities_created += 1
                        discovered.append(periph_name)
                    # MCU drives motors
                    if not self._relation_exists(mcu_entity["id"], result["id"]):
                        self.ce.create_relation(Relation(
                            project_id=project_id,
                            source_entity_id=mcu_entity["id"],
                            target_entity_id=result["id"],
                            relation_type=RelationType.DRIVES,
                            metadata={"signal": sig_name, "auto_discovered": True},
                            confidence=0.8,
                        ))
                        relations_created += 1
            else:
                # One entity per category, list all signals
                sig_names = [s[0] for s in items]
                periph_name = component_type
                # Disambiguate if multiple of same type (e.g., "IR Sensor (left)")
                if len(items) > 1:
                    periph_name = f"{component_type} ({len(items)} channels)"
                result = self._find_or_create_entity(
                    project_id=project_id,
                    entity_type=EntityType.ELECTRICAL_PART,
                    name=periph_name,
                    source_ref=f"runtime:peripheral:{cat}",
                    metadata={
                        "component_category": cat,
                        "discovered_from": "telemetry",
                        "signals": sig_names,
                    },
                )
                if result["created"]:
                    entities_created += 1
                    discovered.append(periph_name)

                # Determine relation type: sensors → reads_from, actuators → drives
                is_actuator = cat in ("motor_output", "servo")
                rel_type = RelationType.DRIVES if is_actuator else RelationType.READS_FROM
                if not self._relation_exists(mcu_entity["id"], result["id"]):
                    self.ce.create_relation(Relation(
                        project_id=project_id,
                        source_entity_id=mcu_entity["id"],
                        target_entity_id=result["id"],
                        relation_type=rel_type,
                        metadata={"signals": sig_names, "auto_discovered": True},
                        confidence=0.8,
                    ))
                    relations_created += 1

        return {
            "entities_created": entities_created,
            "relations_created": relations_created,
            "discovered_peripherals": discovered,
            "mcu": mcu_name,
        }

    # ── Signal classification ─────────────────────────────────────────

    def _classify_signal(self, name: str, data: dict) -> dict:
        """Classify a signal by name pattern, falling back to value range."""
        name_lower = name.lower()

        # Try pattern matching against known signal names
        for pattern, info in self.SENSOR_PATTERNS.items():
            if pattern in name_lower:
                return {"category": info["category"], "component": info["component"]}

        # Fallback: classify by value range
        val = data.get("value", 0) if isinstance(data, dict) else 0
        vmin = data.get("min", val) if isinstance(data, dict) else val
        vmax = data.get("max", val) if isinstance(data, dict) else val

        if vmin >= 0 and vmax <= 1:
            return {"category": "binary_sensor", "component": "Digital Sensor"}
        if vmin >= 0 and vmax <= 1023:
            return {"category": "analog_sensor", "component": "Analog Sensor"}
        if vmin >= -180 and vmax <= 360:
            return {"category": "angle_sensor", "component": "Angle Sensor"}

        return {"category": "unknown", "component": f"Sensor ({name})"}

    # ── MCU detection ─────────────────────────────────────────────────

    def _detect_mcu(self, port_info: dict = None) -> str:
        if not port_info:
            return "Microcontroller"
        vid = port_info.get("vid")
        if vid and vid in self.MCU_VID_MAP:
            return self.MCU_VID_MAP[vid]
        desc = (port_info.get("description") or "").lower()
        if "ch340" in desc:
            return "Arduino Uno (CH340)"
        if "cp210" in desc:
            return "Arduino (CP2102)"
        if "arduino" in desc:
            return "Arduino"
        return "Microcontroller"

    # ── Entity helpers ────────────────────────────────────────────────

    def _find_or_create_entity(self, project_id: str, entity_type: EntityType,
                                name: str, source_ref: str,
                                metadata: dict) -> dict:
        """Find existing entity by source_ref or create new. Returns {"id", "created"}."""
        existing = self.ce.get_entities_by_project(project_id)
        for e in existing:
            if e.source_ref == source_ref:
                return {"id": e.id, "created": False}

        ent = Entity(
            project_id=project_id,
            entity_type=entity_type,
            name=name,
            source=SourceType.RUNTIME,
            source_ref=source_ref,
            metadata=metadata,
        )
        self.ce.create_entity(ent)
        return {"id": ent.id, "created": True}

    def _relation_exists(self, source_id: str, target_id: str) -> bool:
        for r in self.ce.get_relations_for_entity(source_id):
            if r.target_entity_id == target_id:
                return True
        return False

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _signal_to_label(sig_name: str) -> str:
        """Turn 'left_motor' into 'Left', 'right_motor' into 'Right', etc."""
        parts = sig_name.lower().replace("_", " ").split()
        # Remove the category word itself (motor, sensor, etc.)
        label_parts = [p for p in parts if p not in ("motor", "sensor", "value",
                                                      "pwm", "output", "input")]
        if label_parts:
            return " ".join(w.capitalize() for w in label_parts)
        return sig_name.replace("_", " ").title()
