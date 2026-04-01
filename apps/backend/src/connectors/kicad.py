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
        net_components: dict[str, list[str]] = {}

        sch_files = glob.glob(os.path.join(self.project_path, '**', '*.kicad_sch'), recursive=True)

        for sch_file in sch_files:
            try:
                with open(sch_file, 'r', errors='replace') as f:
                    content = f.read()
            except (OSError, IOError):
                continue

            # Extract symbol blocks with Reference and Value properties
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

            # Extract nets
            net_labels = re.findall(r'\((?:label|net_name)\s+"([^"]+)"', content)
            for net_name in set(net_labels):
                if net_name not in net_components:
                    net_components[net_name] = []

            # Extract pin-to-net assignments from wire/pin structures
            # Simplified: find (net "NAME") near (pin "REF" "PIN") patterns
            pin_nets = re.findall(
                r'\(pin\s+"([^"]+)"\s+"([^"]+)".*?\(net\s+"([^"]+)"',
                content, re.DOTALL
            )
            for comp_ref, pin, net_name in pin_nets:
                net_components.setdefault(net_name, [])
                if comp_ref in component_by_ref and comp_ref not in net_components[net_name]:
                    net_components[net_name].append(comp_ref)

        # Create net entities and CONNECTED_TO relations
        for net_name, comp_refs in net_components.items():
            if not net_name or net_name.startswith('unconnected'):
                continue
            net_ent = Entity(
                project_id=self.project_id,
                entity_type=EntityType.INTERFACE,
                name=net_name,
                source=SourceType.KICAD,
                source_ref=f"net:{net_name}",
                metadata={"net_type": "electrical"},
            )
            entities.append(net_ent)

            # Connect components sharing this net
            for ref in comp_refs:
                if ref in component_by_ref:
                    rel = Relation(
                        project_id=self.project_id,
                        source_entity_id=component_by_ref[ref].id,
                        target_entity_id=net_ent.id,
                        relation_type=RelationType.CONNECTED_TO,
                        metadata={"net": net_name},
                    )
                    relations.append(rel)

            # Also create direct CONNECTED_TO between components on same net
            for i in range(len(comp_refs)):
                for j in range(i + 1, len(comp_refs)):
                    if comp_refs[i] in component_by_ref and comp_refs[j] in component_by_ref:
                        rel = Relation(
                            project_id=self.project_id,
                            source_entity_id=component_by_ref[comp_refs[i]].id,
                            target_entity_id=component_by_ref[comp_refs[j]].id,
                            relation_type=RelationType.CONNECTED_TO,
                            metadata={"via_net": net_name},
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
