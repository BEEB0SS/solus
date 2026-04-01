"""
Solus AI Agent — Claude-powered robotics debugging assistant.
Routes queries to specialized handlers with full system context.
"""

import json
import os
import sys

import anthropic

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'packages', 'shared-types', 'src'))
from models import AgentQuery, AgentResponse, _uid, _now


class SolusAgent:

    def __init__(self, context_engine=None, memory_store=None):
        self.context_engine = context_engine
        self.memory_store = memory_store

        api_key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            self.client = anthropic.Anthropic(api_key=api_key)
            self.model = "claude-sonnet-4-5-20250929"
            self.available = True
        else:
            self.client = None
            self.model = None
            self.available = False

    async def query(self, agent_query: AgentQuery) -> AgentResponse:
        try:
            handlers = {
                "debug": self._handle_debug,
                "search_parts": self._handle_search_parts,
                "extract_values": self._handle_extract_values,
                "impact_analysis": self._handle_impact_analysis,
                "general": self._handle_general,
                "plan": self._handle_plan,
            }
            handler = handlers.get(agent_query.query_type, self._handle_general)
            return await handler(agent_query)
        except Exception as e:
            print(f"[agent] error handling query: {e}")
            return AgentResponse(
                query_id=agent_query.id,
                response_text=f"Agent error: {str(e)}",
                confidence=0.0,
            )

    # ── Handlers ──────────────────────────────────────────────────────

    async def _handle_debug(self, q: AgentQuery) -> AgentResponse:
        ctx = self._build_context(q)
        subgraph = ctx["subgraph"]
        recent_changes = ctx["recent_changes"]
        memory_hits = ctx["memory_hits"]
        source_code = ctx["source_code"]

        # Build electrical components list
        electrical_parts = []
        if subgraph and "entities" in subgraph:
            for e in subgraph["entities"]:
                if e.get("entity_type") == "electrical_part":
                    designator = e.get("metadata", {}).get("designator", e.get("name", ""))
                    electrical_parts.append(f"{designator}: {e['name']} - {e.get('description', '')}")

        subgraph_str = json.dumps(subgraph, indent=2, default=str)[:3000] if subgraph else "No system graph available."

        source_code_str = ""
        for filename, content in source_code.items():
            source_code_str += f"--- {filename} ---\n{content}\n\n"
        if not source_code_str:
            source_code_str = "No source code files found in graph."

        electrical_str = "\n".join(electrical_parts) if electrical_parts else "No electrical components found in graph."

        memory_str = json.dumps(memory_hits, indent=2, default=str) if memory_hits else "No similar past issues found."

        changes_str = json.dumps(recent_changes, indent=2, default=str) if recent_changes else "No recent changes."

        system_prompt = """You are Solus, a robotics debugging assistant with access to the robot's full system context: source code, electronic schematic, mechanical design, and live telemetry data.

When diagnosing:
1. LIKELY CAUSE — name the specific component, parameter, variable, and file. Be precise.
2. ROOT CAUSE — trace through the system: code variable -> driver behavior -> motor physics. Explain WHY this value causes the observed behavior.
3. SUGGESTED FIX — specific values with engineering reasoning.
4. CORRECTED CODE — complete, compilable Arduino sketch. Not a snippet. The full file.

Reference specific: file names, component designators (U1, U2), signal names from telemetry, datasheet specs. Be concise. Engineers read this."""

        user_prompt = f"""ROBOT SYSTEM GRAPH:
{subgraph_str}

SOURCE CODE FILES:
{source_code_str}

ELECTRICAL COMPONENTS:
{electrical_str}

RECENT CHANGES:
{changes_str}

SIMILAR PAST ISSUES:
{memory_str}

User query: {q.query}"""

        response_text = self._call_llm(system_prompt, user_prompt)

        return AgentResponse(
            query_id=q.id,
            response_text=response_text,
            sources=list(source_code.keys()) + [p.split(":")[0] for p in electrical_parts],
            confidence=0.85,
        )

    async def _handle_search_parts(self, q: AgentQuery) -> AgentResponse:
        ctx = self._build_context(q)
        subgraph = ctx["subgraph"]

        # Identify voltage rails, MCU pins, and buses from graph
        voltage_rails = []
        mcu_pins = []
        buses = []
        if subgraph and "entities" in subgraph:
            for e in subgraph["entities"]:
                name = e.get("name", "").upper()
                etype = e.get("entity_type", "")
                if etype == "interface" and any(v in name for v in ["VCC", "5V", "3V3", "VBAT", "GND"]):
                    voltage_rails.append(e["name"])
                if "ATMEGA328P" in name or "MCU" in name:
                    pins = e.get("metadata", {}).get("available_pins", [])
                    mcu_pins.extend(pins)
                if etype == "interface" and any(b in name for b in ["I2C", "SPI", "UART", "SERIAL"]):
                    buses.append(e["name"])

        subgraph_str = json.dumps(subgraph, indent=2, default=str)[:3000] if subgraph else "No system graph."

        system_prompt = "You are Solus, a robotics parts recommendation assistant. Check voltage compatibility with existing rails, pin availability on the MCU, protocol compatibility. Return: part name, manufacturer, key specs, WHY it's compatible with this specific system, wiring instructions, any supporting resistors/caps needed."

        user_prompt = f"""Given this robot system, recommend a component for: {q.query}

ROBOT SYSTEM GRAPH:
{subgraph_str}

EXISTING VOLTAGE RAILS: {', '.join(voltage_rails) if voltage_rails else 'Unknown — check schematic'}
AVAILABLE MCU PINS: {', '.join(mcu_pins) if mcu_pins else 'Unknown — check schematic'}
COMMUNICATION BUSES: {', '.join(buses) if buses else 'Unknown — check schematic'}"""

        response_text = self._call_llm(system_prompt, user_prompt)

        return AgentResponse(
            query_id=q.id,
            response_text=response_text,
            confidence=0.75,
        )

    async def _handle_extract_values(self, q: AgentQuery) -> AgentResponse:
        ctx = self._build_context(q)
        subgraph_str = json.dumps(ctx["subgraph"], indent=2, default=str)[:3000] if ctx["subgraph"] else "No context."
        source_str = ""
        for filename, content in ctx["source_code"].items():
            source_str += f"--- {filename} ---\n{content}\n\n"

        system_prompt = "You are Solus, a robotics parameter extraction assistant. For each value, state: the value, the unit, confidence level (high/medium/low/uncertain), and the source. NEVER fabricate values. If uncertain, say so explicitly."

        user_prompt = f"""Extract the requested parameter values from the provided context.

SYSTEM CONTEXT:
{subgraph_str}

SOURCE CODE:
{source_str if source_str else 'No source code available.'}

Request: {q.query}"""

        response_text = self._call_llm(system_prompt, user_prompt)

        return AgentResponse(
            query_id=q.id,
            response_text=response_text,
            confidence=0.7,
        )

    async def _handle_impact_analysis(self, q: AgentQuery) -> AgentResponse:
        impact_list = []
        entity_id = q.context_entity_ids[0] if q.context_entity_ids else None

        if entity_id and self.context_engine:
            impact_list = self.context_engine.analyze_impact(entity_id, q.project_id)

        impact_str = json.dumps(impact_list, indent=2, default=str) if impact_list else "No downstream impacts found."

        ctx = self._build_context(q)
        subgraph_str = json.dumps(ctx["subgraph"], indent=2, default=str)[:3000] if ctx["subgraph"] else "No system graph."

        system_prompt = "You are Solus, a robotics impact analysis assistant. For each affected entity, explain HOW it is affected and what the engineer needs to do."

        user_prompt = f"""This component changed. Here are the downstream entities affected:

{impact_str}

ROBOT SYSTEM GRAPH:
{subgraph_str}

Context: {q.query}"""

        response_text = self._call_llm(system_prompt, user_prompt)

        return AgentResponse(
            query_id=q.id,
            response_text=response_text,
            structured_data={"impact_list": impact_list},
            confidence=0.8,
        )

    async def _handle_general(self, q: AgentQuery) -> AgentResponse:
        ctx = self._build_context(q)
        subgraph_str = json.dumps(ctx["subgraph"], indent=2, default=str)[:3000] if ctx["subgraph"] else "No system graph."

        system_prompt = "You are Solus, a robotics engineering assistant with access to the robot's full system context."

        user_prompt = f"""Given this robot system, answer the following question.

ROBOT SYSTEM GRAPH:
{subgraph_str}

Question: {q.query}"""

        response_text = self._call_llm(system_prompt, user_prompt)

        return AgentResponse(
            query_id=q.id,
            response_text=response_text,
            confidence=0.7,
        )

    async def _handle_plan(self, q: AgentQuery) -> AgentResponse:
        ctx = self._build_context(q)
        subgraph_str = json.dumps(ctx["subgraph"], indent=2, default=str)[:3000] if ctx["subgraph"] else "No system graph."
        source_str = ""
        for filename, content in ctx["source_code"].items():
            source_str += f"--- {filename} ---\n{content}\n\n"

        system_prompt = "You are Solus, a robotics integration planning assistant. Provide: step-by-step plan, components needed, wiring changes, code changes, testing procedure."

        user_prompt = f"""Generate a detailed integration plan for this robot system.

ROBOT SYSTEM GRAPH:
{subgraph_str}

SOURCE CODE:
{source_str if source_str else 'No source code available.'}

Plan request: {q.query}"""

        response_text = self._call_llm(system_prompt, user_prompt)

        return AgentResponse(
            query_id=q.id,
            response_text=response_text,
            confidence=0.7,
        )

    # ── Helpers ───────────────────────────────────────────────────────

    def _build_context(self, q: AgentQuery) -> dict:
        subgraph = None
        recent_changes = []
        memory_hits = []
        source_code = {}

        if self.context_engine:
            try:
                subgraph = self.context_engine.get_subgraph(q.project_id)
            except Exception as e:
                print(f"[agent] subgraph fetch failed: {e}")

            try:
                recent_changes = self.context_engine.get_recent_changes(q.project_id)
            except Exception as e:
                print(f"[agent] recent changes fetch failed: {e}")

        if self.memory_store:
            try:
                memory_hits = self.memory_store.find_similar(q.query, q.project_id)
            except Exception as e:
                print(f"[agent] memory search failed: {e}")

        # Extract source code from software_module entities
        if subgraph and "entities" in subgraph:
            for entity in subgraph["entities"]:
                if entity.get("entity_type") == "software_module":
                    name = entity.get("name", "")
                    if name.endswith(".ino") or name.endswith(".py"):
                        content = entity.get("metadata", {}).get("file_content", "")
                        if content:
                            source_code[name] = content

        return {
            "subgraph": subgraph,
            "recent_changes": recent_changes,
            "memory_hits": memory_hits,
            "source_code": source_code,
        }

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        if not self.available:
            return "Claude API key not configured. Set CLAUDE_API_KEY or ANTHROPIC_API_KEY."
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}]
            )
            return response.content[0].text
        except Exception as e:
            return f"Claude API error: {str(e)}"
