"""api/db.py — SQLite-backed trace store for pipeline events."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS traces (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id        TEXT    NOT NULL,
    step          TEXT    NOT NULL,
    status        TEXT    NOT NULL,
    duration_ms   INTEGER NOT NULL,
    output_json   TEXT    NOT NULL DEFAULT '{}',
    chunks_json   TEXT    NOT NULL DEFAULT '[]',
    skill_version TEXT    NOT NULL DEFAULT '',
    timestamp     TEXT    NOT NULL
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_traces_doc_id ON traces(doc_id);
"""

CREATE_DOCUMENT_KEYS_SQL = """
CREATE TABLE IF NOT EXISTS document_keys (
    company_id TEXT NOT NULL,
    supplier_key TEXT NOT NULL,
    number_key TEXT NOT NULL,
    date_key TEXT NOT NULL DEFAULT '',
    doc_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (company_id, supplier_key, number_key, date_key)
);
"""


class TraceStore:
    """Thread-safe SQLite trace store."""

    def __init__(self, db_path: str = "./traces.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_TABLE_SQL)
            conn.execute(CREATE_INDEX_SQL)
            conn.execute(CREATE_DOCUMENT_KEYS_SQL)
            conn.commit()
        self._backfill_document_keys()

    def _backfill_document_keys(self) -> None:
        """Seed duplicate keys from completed business records already in SQLite."""
        import re

        diagnostic_id = re.compile(
            r"^(?:debug(?:-|$)|test(?:-|$)|e2e(?:-|$)|tol\d|demo(?:-|$)|=+$)",
            re.IGNORECASE,
        )
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT t.doc_id, t.output_json
                   FROM traces t
                   WHERE t.step='extract' AND t.status='success'
                     AND EXISTS (
                       SELECT 1 FROM traces d
                       WHERE d.doc_id=t.doc_id AND d.step IN ('accept','escalate')
                     )
                   ORDER BY t.id ASC"""
            ).fetchall()
        for row in rows:
            doc_id = row["doc_id"]
            if diagnostic_id.match(doc_id):
                continue
            try:
                fields = json.loads(row["output_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            company_id = fields.get("company_id")
            if company_id not in {"company_a", "company_b"}:
                continue
            self.register_document_key(
                company_id=company_id,
                supplier=fields.get("supplier") or "",
                number=fields.get("number") or "",
                date=fields.get("date") or "",
                doc_id=doc_id,
            )

    def write(
        self,
        doc_id: str,
        step: str,
        status: str,
        duration_ms: int,
        output: dict | str = None,
        chunks: list = None,
        skill_version: str = "",
    ) -> int:
        """
        Write a trace event. Returns the row id.
        """
        output_json = json.dumps(output, ensure_ascii=False) if isinstance(output, dict) else (output or "{}")
        chunks_json = json.dumps(chunks or [], ensure_ascii=False)
        timestamp = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO traces
                   (doc_id, step, status, duration_ms, output_json, chunks_json, skill_version, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, step, status, duration_ms, output_json, chunks_json, skill_version, timestamp),
            )
            conn.commit()
            return cur.lastrowid

    def get_by_doc_id(self, doc_id: str) -> list[dict]:
        """Return all trace rows for a doc_id, ordered by timestamp."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM traces WHERE doc_id = ? ORDER BY timestamp ASC",
                (doc_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def doc_id_exists(self, doc_id: str) -> bool:
        """Return True if any trace row exists for this doc_id."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM traces WHERE doc_id = ? LIMIT 1", (doc_id,)
            ).fetchone()
        return row is not None

    def register_document_key(
        self,
        company_id: str,
        supplier: str,
        number: str,
        date: str,
        doc_id: str,
    ) -> Optional[str]:
        """Register an invoice identity and return the prior doc ID on a duplicate.

        Requires supplier and invoice number. Date is part of the key to avoid
        flagging legitimate number reuse across dates. Replayed requests with the
        same doc_id are idempotent and do not count as duplicates.
        """
        import re
        import unicodedata
        from datetime import datetime

        def key(value: str) -> str:
            value = unicodedata.normalize("NFKD", str(value or "")).casefold()
            value = "".join(ch for ch in value if not unicodedata.combining(ch))
            # Ignore visual punctuation so FAC-123 and FAC/123 normalize equally.
            return re.sub(r"[^a-z0-9]+", "", value)

        supplier_key, number_key, date_key = key(supplier), key(number), key(date)
        if not supplier_key or not number_key:
            return None

        raw_date = str(date or "").strip()
        for date_format in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y"):
            try:
                date_key = datetime.strptime(raw_date, date_format).date().isoformat()
                break
            except ValueError:
                continue

        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            # Serialize check-then-insert so simultaneous source triggers cannot
            # both accept the same invoice identity.
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT doc_id FROM document_keys
                   WHERE company_id=? AND supplier_key=? AND number_key=? AND date_key=?""",
                (company_id, supplier_key, number_key, date_key),
            ).fetchone()
            if row:
                prior_doc_id = row["doc_id"] if row["doc_id"] != doc_id else None
                conn.commit()
                return prior_doc_id
            conn.execute(
                """INSERT INTO document_keys
                   (company_id, supplier_key, number_key, date_key, doc_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (company_id, supplier_key, number_key, date_key, doc_id, created_at),
            )
            conn.commit()
        return None

    def list_doc_ids(self, limit: int = 100) -> list[dict]:
        """Return the most recent unique doc_ids with their final decision and timestamp."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT doc_id,
                          MAX(timestamp) AS last_seen,
                          MIN(timestamp) AS first_seen,
                          SUM(duration_ms) AS total_ms,
                          (SELECT CASE t2.step
                                    WHEN 'accept' THEN 'ACCEPTED'
                                    WHEN 'escalate' THEN 'ESCALATED'
                                    WHEN 'fail' THEN 'FAILED'
                                    ELSE NULL END
                           FROM traces t2
                           WHERE t2.doc_id = traces.doc_id
                             AND t2.step IN ('accept', 'escalate', 'fail')
                           ORDER BY t2.id DESC LIMIT 1) AS decision
                   FROM traces
                   GROUP BY doc_id
                   ORDER BY last_seen DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_extraction_fields(self, doc_id: str) -> dict:
        """Return extracted fields with the latest human review overlaid."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT step, output_json FROM traces WHERE doc_id = ? AND step IN ('extract', 'review') ORDER BY id ASC",
                (doc_id,),
            ).fetchall()
        fields: dict = {}
        for row in rows:
            try:
                output = json.loads(row["output_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if row["step"] == "extract":
                fields.update(output)
            elif row["step"] == "review":
                fields.update(output.get("fields", {}))
        return fields

    def get_latest_output(self, doc_id: str, step: str) -> dict:
        """Return the latest JSON output for a named pipeline step."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT output_json FROM traces WHERE doc_id = ? AND step = ? ORDER BY id DESC LIMIT 1",
                (doc_id, step),
            ).fetchone()
        if not row:
            return {}
        try:
            value = json.loads(row["output_json"] or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def health_check(self) -> bool:
        """Return True if database is accessible."""
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False
