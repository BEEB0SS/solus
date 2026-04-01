"""
Solus Onshape connector.
Syncs parts and assemblies from Onshape REST API v6.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'packages', 'shared-types', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
from models import Entity, Relation, EntityType, RelationType, SourceType

BASE_URL = "https://cad.onshape.com/api/v6"
HEADERS = {'Accept': 'application/json', 'Content-Type': 'application/json'}


class OnshapeConnector:
    def __init__(self, document_id: str, workspace_id: str, project_id: str,
                 access_key: str = "", secret_key: str = ""):
        self.project_id = project_id
        self.ak = access_key
        self.sk = secret_key
        self.eid = ""

        # Parse full Onshape URL if provided
        if document_id and ("http" in document_id or "onshape.com" in document_id):
            match = re.match(r'.*/documents/([a-f0-9]+)/w/([a-f0-9]+)/e/([a-f0-9]+)', document_id)
            if match:
                self.did = match.group(1)
                self.wid = match.group(2)
                self.eid = match.group(3)
            else:
                # Try without element: /documents/{did}/w/{wid}
                match2 = re.match(r'.*/documents/([a-f0-9]+)/w/([a-f0-9]+)', document_id)
                if match2:
                    self.did = match2.group(1)
                    self.wid = match2.group(2)
                else:
                    # Try just document id from URL: /documents/{did}
                    match3 = re.match(r'.*/documents/([a-f0-9]+)', document_id)
                    self.did = match3.group(1) if match3 else document_id
                    self.wid = workspace_id
        else:
            self.did = document_id
            self.wid = workspace_id

    def _get(self, path: str) -> dict | list | None:
        try:
            resp = requests.get(
                f"{BASE_URL}{path}",
                auth=(self.ak, self.sk),
                headers=HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f"[onshape] request failed: {path} — {e}")
            return None

    def sync(self) -> dict:
        if not self.ak or not self.sk:
            return {"items": [], "entities": [], "relations": [],
                    "warning": "Onshape API keys not configured"}

        items = []
        entities = []
        relations = []

        # Get document metadata
        doc = self._get(f"/documents/{self.did}")
        doc_name = doc.get("name", "Onshape Document") if doc else "Onshape Document"

        # Auto-fetch workspace_id if empty
        if not self.wid and doc:
            dw = doc.get("defaultWorkspace")
            if dw and dw.get("id"):
                self.wid = dw["id"]
                print(f"[onshape] auto-resolved workspace: {self.wid}")
            else:
                print("[onshape] no defaultWorkspace found in document")
                return {"items": items, "entities": entities, "relations": []}

        # List elements
        elements = self._get(f"/documents/d/{self.did}/w/{self.wid}/elements")
        if not elements:
            return {"items": items, "entities": entities, "relations": relations}

        for elem in elements:
            eid = elem.get("id", "")
            etype = elem.get("type", "")
            ename = elem.get("name", "")

            if etype == "Part Studio":
                self._ingest_part_studio(eid, ename, items, entities)
            elif etype == "Assembly":
                self._ingest_assembly(eid, ename, items, entities, relations)

        return {"items": items, "entities": entities, "relations": relations}

    def _ingest_part_studio(self, eid: str, studio_name: str,
                            items: list, entities: list):
        parts = self._get(f"/parts/d/{self.did}/w/{self.wid}/e/{eid}")
        if not parts:
            return

        # Try to get mass properties
        mass_props = self._get(f"/partstudios/d/{self.did}/w/{self.wid}/e/{eid}/massproperties")
        mass_by_part: dict[str, dict] = {}
        if mass_props and "bodies" in mass_props:
            for pid, body in mass_props["bodies"].items():
                mass_by_part[pid] = {
                    "mass": body.get("mass", [0])[0] if isinstance(body.get("mass"), list) else body.get("mass"),
                    "volume": body.get("volume", [0])[0] if isinstance(body.get("volume"), list) else body.get("volume"),
                }

        # Fetch per-part bounding boxes (the studio-level endpoint is a single aggregate)
        bbox_by_part: dict[str, dict] = {}
        for part in parts:
            pid = part.get("partId", "")
            if not pid:
                continue
            box = self._get(f"/parts/d/{self.did}/w/{self.wid}/e/{eid}/partid/{pid}/boundingboxes")
            if box and isinstance(box, dict) and "lowX" in box:
                bbox_by_part[pid] = {
                    "minX": box["lowX"], "maxX": box["highX"],
                    "minY": box["lowY"], "maxY": box["highY"],
                    "minZ": box["lowZ"], "maxZ": box["highZ"],
                }

        for part in parts:
            part_id = part.get("partId", "")
            name = part.get("name", "Unnamed Part")
            material = part.get("material", {})
            mat_name = material.get("displayName", "") if material else ""

            metadata = {"partId": part_id, "elementId": eid, "material": mat_name}
            if part_id in mass_by_part:
                metadata.update(mass_by_part[part_id])

            # Compute bounding box dimensions if available
            dims_mm = None
            if part_id in bbox_by_part:
                box = bbox_by_part[part_id]
                lx = abs(box.get("maxX", 0) - box.get("minX", 0)) * 1000
                ly = abs(box.get("maxY", 0) - box.get("minY", 0)) * 1000
                lz = abs(box.get("maxZ", 0) - box.get("minZ", 0)) * 1000
                dims_mm = sorted([lx, ly, lz], reverse=True)
                metadata["dimensions_mm"] = {"x": round(lx, 1), "y": round(ly, 1), "z": round(lz, 1)}

            # Improve generic part names
            if re.match(r'^Part\s*\d*$', name, re.IGNORECASE):
                name = self._improve_part_name(name, mat_name, dims_mm, studio_name)
                metadata["original_name"] = part.get("name", "")

            ent = Entity(
                project_id=self.project_id,
                entity_type=EntityType.MECHANICAL_PART,
                name=name,
                source=SourceType.ONSHAPE,
                source_ref=f"{self.did}/w/{self.wid}/e/{eid}/p/{part_id}",
                metadata=metadata,
            )
            entities.append(ent)
            items.append({
                "ref": f"{eid}/{part_id}",
                "name": name,
                "entity_type": "mechanical_part",
                "metadata": metadata,
            })

    def _ingest_assembly(self, eid: str, asm_name: str,
                         items: list, entities: list, relations: list):
        asm = self._get(f"/assemblies/d/{self.did}/w/{self.wid}/e/{eid}")
        if not asm:
            return

        root = asm.get("rootAssembly", {})
        instances = root.get("instances", [])
        features = root.get("features", [])

        instance_entity_ids: dict[str, str] = {}

        for inst in instances:
            inst_id = inst.get("id", "")
            name = inst.get("name", "Instance")
            part_id = inst.get("partId", "")

            ent = Entity(
                project_id=self.project_id,
                entity_type=EntityType.MECHANICAL_PART,
                name=name,
                source=SourceType.ONSHAPE,
                source_ref=f"{self.did}/w/{self.wid}/e/{eid}/i/{inst_id}",
                metadata={"instanceId": inst_id, "partId": part_id, "elementId": eid},
            )
            entities.append(ent)
            instance_entity_ids[inst_id] = ent.id
            items.append({
                "ref": f"{eid}/{inst_id}",
                "name": name,
                "entity_type": "mechanical_part",
                "metadata": {"instanceId": inst_id},
            })

        # Process mates as relations
        for feat in features:
            feat_type = feat.get("featureType", "")
            if feat_type != "mate":
                continue
            mate_data = feat.get("featureData", {})
            mate_type = mate_data.get("mateType", "")
            connectors = mate_data.get("matedEntities", [])

            if len(connectors) >= 2:
                occ0 = connectors[0].get("matedOccurrence", [""])[0] if connectors[0].get("matedOccurrence") else ""
                occ1 = connectors[1].get("matedOccurrence", [""])[0] if connectors[1].get("matedOccurrence") else ""
                eid0 = instance_entity_ids.get(occ0)
                eid1 = instance_entity_ids.get(occ1)

                if eid0 and eid1:
                    if mate_type in ("REVOLUTE", "SLIDER"):
                        joint_type = mate_type.lower()
                    elif mate_type == "FASTENED":
                        joint_type = "fixed"
                    else:
                        joint_type = mate_type.lower()

                    rel = Relation(
                        project_id=self.project_id,
                        source_entity_id=eid0,
                        target_entity_id=eid1,
                        relation_type=RelationType.CONNECTED_TO,
                        metadata={"joint_type": joint_type},
                    )
                    relations.append(rel)

    @staticmethod
    def _improve_part_name(name: str, material: str, dims_mm: list[float] | None,
                           studio_name: str) -> str:
        """Improve generic 'Part N' names using dimensions, material, and studio context."""
        suffix_parts = []

        # Add dimensions if available
        if dims_mm and all(d > 0.1 for d in dims_mm):
            dim_str = "\u00d7".join(f"{d:.0f}" for d in dims_mm)
            suffix_parts.append(f"{dim_str}mm")

        # Classify by shape from dimensions
        classification = ""
        if dims_mm and all(d > 0.1 for d in dims_mm):
            largest, middle, smallest = dims_mm
            if smallest > 0:
                flat_ratio = largest / smallest
                aspect = largest / middle if middle > 0 else 1
                if flat_ratio > 8 and aspect < 3:
                    classification = "Plate"
                elif flat_ratio > 5:
                    classification = "Chassis"
                elif aspect > 4:
                    classification = "Shaft"
                elif 2.5 < aspect < 5 and middle / smallest < 2:
                    classification = "Wheel"
                elif largest < 20:
                    classification = "Bracket"
                elif largest < 40:
                    classification = "Mount"

        # Add material hint
        if material:
            suffix_parts.append(material)

        # Build improved name
        if classification:
            base = f"{classification}"
        elif studio_name and studio_name.lower() not in ("part studio", "parts"):
            base = studio_name
        else:
            base = name

        if suffix_parts:
            return f"{base} ({', '.join(suffix_parts)})"
        return base

    def get_assembly_structure(self) -> dict:
        elements = self._get(f"/documents/d/{self.did}/w/{self.wid}/elements")
        if not elements:
            return {}
        for elem in elements:
            if elem.get("type") == "Assembly":
                eid = elem["id"]
                result = self._get(f"/assemblies/d/{self.did}/w/{self.wid}/e/{eid}")
                return result or {}
        return {}

    def get_parts(self) -> list[dict]:
        elements = self._get(f"/documents/d/{self.did}/w/{self.wid}/elements")
        if not elements:
            return []
        parts = []
        for elem in elements:
            if elem.get("type") == "Part Studio":
                eid = elem["id"]
                studio_parts = self._get(f"/partstudios/d/{self.did}/w/{self.wid}/e/{eid}/parts")
                if studio_parts:
                    for p in studio_parts:
                        parts.append({
                            "name": p.get("name", ""),
                            "partId": p.get("partId", ""),
                            "elementId": eid,
                        })
        return parts
