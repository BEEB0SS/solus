"""
Solus SQLite database.
DB stored at ~/.solus/solus.db. WAL mode, foreign keys ON.
JSON fields use json.dumps() on write, json.loads() on read.
"""

import os
import sqlite3


DB_PATH = os.path.join(os.path.expanduser("~"), ".solus", "solus.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            source TEXT DEFAULT 'manual',
            source_ref TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE INDEX IF NOT EXISTS idx_entities_project_type
            ON entities(project_id, entity_type);

        CREATE TABLE IF NOT EXISTS relations (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            source_entity_id TEXT NOT NULL,
            target_entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            confidence REAL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (source_entity_id) REFERENCES entities(id),
            FOREIGN KEY (target_entity_id) REFERENCES entities(id)
        );

        CREATE INDEX IF NOT EXISTS idx_relations_project_src_tgt
            ON relations(project_id, source_entity_id, target_entity_id);

        CREATE TABLE IF NOT EXISTS team_members (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT DEFAULT '',
            email TEXT DEFAULT '',
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS source_connections (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            name TEXT NOT NULL,
            config TEXT DEFAULT '{}',
            last_synced_at TEXT,
            status TEXT DEFAULT 'disconnected',
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id TEXT PRIMARY KEY,
            source_connection_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            data TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_connection_id) REFERENCES source_connections(id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS change_events (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            source_connection_id TEXT NOT NULL,
            change_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            entity_name TEXT NOT NULL,
            description TEXT DEFAULT '',
            diff_data TEXT DEFAULT '{}',
            impacted_entity_ids TEXT DEFAULT '[]',
            attributed_to TEXT DEFAULT '',
            acknowledged INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE INDEX IF NOT EXISTS idx_change_events_project
            ON change_events(project_id);

        CREATE TABLE IF NOT EXISTS runtime_packets (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            source TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            signals TEXT DEFAULT '[]',
            status TEXT DEFAULT 'healthy',
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS anomalies (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            runtime_packet_id TEXT DEFAULT '',
            signal_name TEXT DEFAULT '',
            expected_range TEXT DEFAULT '(0, 1)',
            actual_value REAL DEFAULT 0.0,
            severity TEXT DEFAULT 'warning',
            description TEXT DEFAULT '',
            pattern_type TEXT DEFAULT '',
            evidence TEXT DEFAULT '',
            expected TEXT DEFAULT '',
            affected_entity_ids TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS issues (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'open',
            related_entity_ids TEXT DEFAULT '[]',
            reported_by TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS fixes (
            id TEXT PRIMARY KEY,
            issue_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            description TEXT DEFAULT '',
            steps TEXT DEFAULT '[]',
            applied_by TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (issue_id) REFERENCES issues(id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS simulation_runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            model_path TEXT DEFAULT '',
            parameters TEXT DEFAULT '{}',
            results TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS agent_queries (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            query TEXT DEFAULT '',
            query_type TEXT DEFAULT 'general',
            context_entity_ids TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS agent_responses (
            id TEXT PRIMARY KEY,
            query_id TEXT NOT NULL,
            response_text TEXT DEFAULT '',
            structured_data TEXT DEFAULT '{}',
            sources TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (query_id) REFERENCES agent_queries(id)
        );

        CREATE TABLE IF NOT EXISTS semantic_memory (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            content TEXT DEFAULT '',
            content_type TEXT DEFAULT '',
            metadata TEXT DEFAULT '{}',
            embedding TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE INDEX IF NOT EXISTS idx_semantic_memory_project_type
            ON semantic_memory(project_id, content_type);
    """)

    conn.commit()
    conn.close()
    print(f"[database] initialized at {DB_PATH}")


if __name__ == "__main__":
    init_db()
