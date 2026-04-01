"""
Solus Memory Store — TF-IDF semantic search over SQLite semantic_memory table.
Standard library only (no numpy).
"""

import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'packages', 'shared-types', 'src'))
from models import SemanticMemoryItem, _uid, _now

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from database import get_connection


STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "of", "in", "to", "for",
    "on", "at", "by", "with", "from", "as", "into", "about", "between",
    "through", "after", "before", "during", "without", "this", "that",
    "these", "those", "it", "its", "and", "but", "or", "not", "no", "so",
    "if", "then", "than", "when", "where", "which", "what", "who", "how",
    "all", "each", "every", "both", "few", "more", "most", "some", "any",
    "other", "new",
}


def _tokenize(text: str) -> list:
    tokens = re.split(r'[\s\W]+', text.lower())
    return [t for t in tokens if t and t not in STOP_WORDS]


class MemoryStore:

    def store(self, item: SemanticMemoryItem) -> SemanticMemoryItem:
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO semantic_memory (id, project_id, content, content_type, metadata, embedding, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.id,
                    item.project_id,
                    item.content,
                    item.content_type,
                    json.dumps(item.metadata),
                    json.dumps(item.embedding) if item.embedding else None,
                    item.created_at,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return item

    def store_issue_fix(self, project_id, issue_title, issue_desc, fix_desc, fix_steps, entity_ids=None):
        content = f"ISSUE: {issue_title}\n{issue_desc}\nFIX: {fix_desc}\nSTEPS: {json.dumps(fix_steps)}"
        item = SemanticMemoryItem(
            project_id=project_id,
            content=content,
            content_type="issue_fix",
            metadata={"entity_ids": entity_ids or []},
        )
        return self.store(item)

    def store_document_chunk(self, project_id, content, doc_name, chunk_index, doc_type="datasheet"):
        item = SemanticMemoryItem(
            project_id=project_id,
            content=content,
            content_type=doc_type,
            metadata={"doc_name": doc_name, "chunk_index": chunk_index},
        )
        return self.store(item)

    def find_similar(self, query, project_id=None, content_type=None, limit=5) -> list:
        conn = get_connection()
        try:
            sql = "SELECT id, project_id, content, content_type, metadata, created_at FROM semantic_memory WHERE 1=1"
            params = []
            if project_id:
                sql += " AND project_id = ?"
                params.append(project_id)
            if content_type:
                sql += " AND content_type = ?"
                params.append(content_type)

            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

        if not rows:
            return []

        # Tokenize query and all documents
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        docs = []
        for row in rows:
            tokens = _tokenize(row["content"])
            docs.append({
                "id": row["id"],
                "content": row["content"],
                "content_type": row["content_type"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                "tokens": tokens,
            })

        # Build vocabulary and IDF
        n_docs = len(docs) + 1  # +1 for query doc
        all_docs_tokens = [d["tokens"] for d in docs] + [query_tokens]

        vocab = set()
        for dt in all_docs_tokens:
            vocab.update(dt)

        doc_freq = {}
        for term in vocab:
            count = sum(1 for dt in all_docs_tokens if term in dt)
            doc_freq[term] = count

        idf = {}
        for term in vocab:
            idf[term] = math.log(n_docs / (1 + doc_freq[term]))

        # Compute TF-IDF vectors and cosine similarity
        def tfidf_vector(tokens):
            vec = {}
            length = len(tokens) if tokens else 1
            token_counts = {}
            for t in tokens:
                token_counts[t] = token_counts.get(t, 0) + 1
            for term, count in token_counts.items():
                tf = count / length
                vec[term] = tf * idf.get(term, 0)
            return vec

        def cosine_sim(a, b):
            common = set(a.keys()) & set(b.keys())
            if not common:
                return 0.0
            dot = sum(a[k] * b[k] for k in common)
            mag_a = math.sqrt(sum(v * v for v in a.values()))
            mag_b = math.sqrt(sum(v * v for v in b.values()))
            if mag_a == 0 or mag_b == 0:
                return 0.0
            return dot / (mag_a * mag_b)

        query_vec = tfidf_vector(query_tokens)

        results = []
        for doc in docs:
            doc_vec = tfidf_vector(doc["tokens"])
            sim = cosine_sim(query_vec, doc_vec)
            results.append({
                "id": doc["id"],
                "content": doc["content"],
                "content_type": doc["content_type"],
                "metadata": doc["metadata"],
                "similarity": round(sim, 4),
            })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]
