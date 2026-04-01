"""
Solus KiCad connector.
Parses .kicad_sch schematics, extracts components and nets, builds entities and relations.
"""

import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'packages', 'shared-types', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models import Entity, Relation, EntityType, RelationType, SourceType


class KiCadConnector:
    def __init__(self, project_path: str, project_id: str):
        self.project_path = os.path.abspath(project_path)
        self.project_id = project_id

    def ingest(self) -> dict:
        items = []
        entities = []
        relations = []
        component_by_ref: dict[str, Entity] = {}
        # net_name -> list of (component_ref, pin_name)
        net_pins: dict[str, list[tuple[str, str]]] = {}

        sch_files = glob.glob(os.path.join(self.project_path, '**', '*.kicad_sch'), recursive=True)

        for sch_file in sch_files:
            try:
                with open(sch_file, 'r', errors='replace') as f:
                    content = f.read()
            except (OSError, IOError):
                continue

            # ── Extract components (symbol blocks with Reference + Value) ──
            symbols = re.findall(
                r'\(symbol\s[^)]*'
                r'.*?\(property\s+"Reference"\s+"([^"]+)"'
                r'.*?\(property\s+"Value"\s+"([^"]+)"',
                content, re.DOTALL
            )

            for ref, value in symbols:
                if ref in component_by_ref or ref.startswith('#'):
                    continue
                category = self._classify_component(ref, value)
                metadata = {"component_category": category, "value": value}

                ent = Entity(
                    project_id=self.project_id,
                    entity_type=EntityType.ELECTRICAL_PART,
                    name=f"{ref} {value}",
                    source=SourceType.KICAD,
                    source_ref=ref,
                    metadata=metadata,
                )
                entities.append(ent)
                component_by_ref[ref] = ent

                items.append({
                    "ref": ref,
                    "name": f"{ref} {value}",
                    "value": value,
                    "entity_type": "electrical_part",
                    "metadata": metadata,
                })

            # ── Extract net→component mappings ──
            # Strategy 1: Parse net_label comments like ";; U1.D5 → U2.PWMA"
            # These appear right after (net_label "NAME" ...) blocks
            net_label_blocks = re.findall(
                r'\(net_label\s+"([^"]+)"[^)]*\).*?(?=\(net_label|\(wire|\Z)',
                content, re.DOTALL
            )
            for match in re.finditer(
                r'\(net_label\s+"([^"]+)".*?\n((?:\s*;;.*\n)*)',
                content
            ):
                net_name = match.group(1)
                comment_block = match.group(2)
                # Parse comments like ";; U1.D5 → U2.PWMA" or ";; U5.OUT → U1.A0"
                for conn_match in re.finditer(
                    r'(\w+)\.(\w+)\s*[→->]+\s*(\w+)\.(\w+)',
                    comment_block
                ):
                    ref1, pin1 = conn_match.group(1), conn_match.group(2)
                    ref2, pin2 = conn_match.group(3), conn_match.group(4)
                    net_pins.setdefault(net_name, [])
                    if ref1 in component_by_ref:
                        entry = (ref1, pin1)
                        if entry not in net_pins[net_name]:
                            net_pins[net_name].append(entry)
                    if ref2 in component_by_ref:
                        entry = (ref2, pin2)
                        if entry not in net_pins[net_name]:
                            net_pins[net_name].append(entry)

            # Strategy 2: Parse (label "NET_NAME") patterns
            label_names = re.findall(r'\((?:label|net_name)\s+"([^"]+)"', content)
            for net_name in set(label_names):
                net_pins.setdefault(net_name, [])

            # Strategy 3: Parse (pin "REF" "PIN") ... (net "NAME") patterns (KiCad netlist format)
            pin_net_matches = re.findall(
                r'\(pin\s+"([^"]+)"\s+"([^"]+)".*?\(net\s+"([^"]+)"',
                content, re.DOTALL
            )
            for comp_ref, pin, net_name in pin_net_matches:
                if comp_ref in component_by_ref:
                    net_pins.setdefault(net_name, [])
                    entry = (comp_ref, pin)
                    if entry not in net_pins[net_name]:
                        net_pins[net_name].append(entry)

            # Strategy 4: Parse wire comments like ";; Motor PWM: U1.D5 → U2.PWMA (MOTOR_L_PWM)"
            for wire_match in re.finditer(
                r';;\s*.*?(\w+)\.(\w+)\s*[→->]+\s*(\w+)\.(\w+)\s*\((\w+)\)',
                content
            ):
                ref1, pin1 = wire_match.group(1), wire_match.group(2)
                ref2, pin2 = wire_match.group(3), wire_match.group(4)
                net_name = wire_match.group(5)
                net_pins.setdefault(net_name, [])
                if ref1 in component_by_ref:
                    entry = (ref1, pin1)
                    if entry not in net_pins[net_name]:
                        net_pins[net_name].append(entry)
                if ref2 in component_by_ref:
                    entry = (ref2, pin2)
                    if entry not in net_pins[net_name]:
                        net_pins[net_name].append(entry)

        # ── Create net (interface) entities and relations ──
        created_pairs: set[tuple[str, str]] = set()

        for net_name, pin_list in net_pins.items():
            if not net_name or net_name.startswith('unconnected'):
                continue

            # Get unique component refs on this net
            comp_refs = list(dict.fromkeys(ref for ref, _ in pin_list))
            if not comp_refs:
                continue

            # Create net entity
            net_ent = Entity(
                project_id=self.project_id,
                entity_type=EntityType.INTERFACE,
                name=net_name,
                source=SourceType.KICAD,
                source_ref=f"net:{net_name}",
                metadata={
                    "net_type": "electrical",
                    "connected_components": comp_refs,
                    "pin_assignments": {ref: pin for ref, pin in pin_list},
                },
            )
            entities.append(net_ent)

            # Connect each component to the net entity
            for ref in comp_refs:
                if ref in component_by_ref:
                    pin = next((p for r, p in pin_list if r == ref), "")
                    rel = Relation(
                        project_id=self.project_id,
                        source_entity_id=component_by_ref[ref].id,
                        target_entity_id=net_ent.id,
                        relation_type=RelationType.CONNECTED_TO,
                        metadata={"net": net_name, "pin": pin},
                    )
                    relations.append(rel)

            # Create direct CONNECTED_TO between all component pairs on this net
            for i in range(len(comp_refs)):
                for j in range(i + 1, len(comp_refs)):
                    ref_a, ref_b = comp_refs[i], comp_refs[j]
                    if ref_a not in component_by_ref or ref_b not in component_by_ref:
                        continue
                    pair = (min(ref_a, ref_b), max(ref_a, ref_b))
                    if pair in created_pairs:
                        continue
                    created_pairs.add(pair)

                    pin_a = next((p for r, p in pin_list if r == ref_a), "")
                    pin_b = next((p for r, p in pin_list if r == ref_b), "")

                    rel = Relation(
                        project_id=self.project_id,
                        source_entity_id=component_by_ref[ref_a].id,
                        target_entity_id=component_by_ref[ref_b].id,
                        relation_type=RelationType.CONNECTED_TO,
                        metadata={
                            "via_net": net_name,
                            "pins": f"{pin_a}\u2192{pin_b}" if pin_a and pin_b else "",
                        },
                    )
                    relations.append(rel)

        return {"items": items, "entities": entities, "relations": relations}

    def _classify_component(self, ref: str, value: str) -> str:
        prefix = re.match(r'^([A-Z]+)', ref)
        prefix = prefix.group(1) if prefix else ""
        value_lower = value.lower()

        if prefix == 'U':
            if 'atmega' in value_lower:
                return 'microcontroller'
            elif 'tb6612' in value_lower:
                return 'motor_driver'
            elif 'hc-sr04' in value_lower or 'hcsr04' in value_lower:
                return 'ultrasonic_sensor'
            elif 'esp32' in value_lower:
                return 'wireless_module'
            elif 'ams1117' in value_lower:
                return 'voltage_regulator'
            elif 'ir' in value_lower:
                return 'sensor'
            return 'ic'
        elif prefix == 'R':
            return 'resistor'
        elif prefix == 'C':
            return 'capacitor'
        elif prefix == 'M':
            return 'motor'
        elif prefix == 'D':
            return 'diode'
        elif prefix == 'J':
            return 'connector'
        elif prefix == 'SW':
            return 'switch'
        return 'component'
