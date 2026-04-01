"""
Solus shared data models.
All data models as Python dataclasses — the single source of truth.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── Enums ──────────────────────────────────────────────────────────────

class EntityType(str, Enum):
    PROJECT = "project"
    TEAM_MEMBER = "team_member"
    MECHANICAL_PART = "mechanical_part"
    ELECTRICAL_PART = "electrical_part"
    SOFTWARE_MODULE = "software_module"
    INTERFACE = "interface"
    RUNTIME_SIGNAL = "runtime_signal"
    DOCUMENT = "document"
    PAPER = "paper"
    ISSUE = "issue"
    FIX = "fix"
    RUN = "run"
    SIMULATION_ASSET = "simulation_asset"
    EXTERNAL_PART_CANDIDATE = "external_part_candidate"


class RelationType(str, Enum):
    CONNECTED_TO = "connected_to"
    DEPENDS_ON = "depends_on"
    CONFIGURED_BY = "configured_by"
    DOCUMENTED_BY = "documented_by"
    PUBLISHES = "publishes"
    SUBSCRIBES_TO = "subscribes_to"
    DRIVES = "drives"
    READS_FROM = "reads_from"
    CHANGED_BY = "changed_by"
    IMPACTS = "impacts"
    OBSERVED_IN = "observed_in"
    RESOLVED_BY = "resolved_by"
    SIMILAR_TO = "similar_to"


class SourceType(str, Enum):
    GITHUB = "github"
    ONSHAPE = "onshape"
    KICAD = "kicad"
    PDF = "pdf"
    MANUAL = "manual"
    RUNTIME = "runtime"


class SignalStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    ERROR = "error"
    UNKNOWN = "unknown"


class ChangeType(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"


class IssueStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"


# ── Dataclasses ────────────────────────────────────────────────────────

@dataclass
class Entity:
    project_id: str
    entity_type: EntityType
    name: str
    description: str = ""
    metadata: dict = field(default_factory=dict)
    source: SourceType = SourceType.MANUAL
    source_ref: str = ""
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class Relation:
    project_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: RelationType
    metadata: dict = field(default_factory=dict)
    confidence: float = 1.0
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class Project:
    name: str
    description: str = ""
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class TeamMember:
    project_id: str
    name: str
    role: str = ""
    email: str = ""
    id: str = field(default_factory=_uid)


@dataclass
class SourceConnection:
    project_id: str
    source_type: SourceType
    name: str
    config: dict = field(default_factory=dict)
    last_synced_at: Optional[str] = None
    status: str = "disconnected"
    id: str = field(default_factory=_uid)


@dataclass
class Snapshot:
    source_connection_id: str
    project_id: str
    data: dict = field(default_factory=dict)
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class ChangeEvent:
    project_id: str
    source_connection_id: str
    change_type: ChangeType
    entity_id: str
    entity_name: str
    description: str = ""
    diff_data: dict = field(default_factory=dict)
    impacted_entity_ids: list = field(default_factory=list)
    attributed_to: str = ""
    acknowledged: bool = False
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class RuntimeSignal:
    name: str
    value: float = 0.0
    unit: str = ""
    timestamp: str = field(default_factory=_now)


@dataclass
class RuntimePacket:
    project_id: str
    source: str
    signals: list = field(default_factory=list)
    status: SignalStatus = SignalStatus.HEALTHY
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=_uid)
    timestamp: str = field(default_factory=_now)


@dataclass
class Anomaly:
    project_id: str
    runtime_packet_id: str = ""
    signal_name: str = ""
    expected_range: tuple = (0, 1)
    actual_value: float = 0.0
    severity: str = "warning"
    description: str = ""
    pattern_type: str = ""
    evidence: str = ""
    expected: str = ""
    affected_entity_ids: list = field(default_factory=list)
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class Issue:
    project_id: str
    title: str
    description: str = ""
    status: IssueStatus = IssueStatus.OPEN
    related_entity_ids: list = field(default_factory=list)
    reported_by: str = ""
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class Fix:
    issue_id: str
    project_id: str
    description: str = ""
    steps: list = field(default_factory=list)
    applied_by: str = ""
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class SimulationRun:
    project_id: str
    model_path: str = ""
    parameters: dict = field(default_factory=dict)
    results: dict = field(default_factory=dict)
    status: str = "pending"
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class AgentQuery:
    project_id: str
    query: str = ""
    query_type: str = "general"
    context_entity_ids: list = field(default_factory=list)
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class AgentResponse:
    query_id: str
    response_text: str = ""
    structured_data: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    confidence: float = 0.0
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)


@dataclass
class SemanticMemoryItem:
    project_id: str
    content: str = ""
    content_type: str = ""
    metadata: dict = field(default_factory=dict)
    embedding: Optional[list] = None
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now)
