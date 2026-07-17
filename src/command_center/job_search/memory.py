"""Private, local memory for job-search relationships and application questions.

This store is deliberately inert: it records operator-authored relationship data
and candidate answers, but it cannot send messages or promote answers into the
standing-answer automation policy.
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 1
PROVENANCE = "operator_private_console"
BUSY_TIMEOUT_MS = 5_000


def _now() -> str:
    return datetime.now(UTC).isoformat()


def normalize_company(value: str) -> str:
    return " ".join(value.casefold().split())


def normalize_question(value: str) -> str:
    return " ".join(value.casefold().split())


def _uuid(value: str) -> str:
    parsed = uuid.UUID(value)
    if str(parsed) != value.lower():
        raise ValueError("relationship id must be a canonical UUID")
    return str(parsed)


class JobSearchMemory:
    """Small SQLite store rooted beside the rest of job-search data."""

    def __init__(self, data_root: Path):
        self.path = Path(data_root) / "job_search_memory.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def _migrate(self) -> None:
        with self._write() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                       version INTEGER PRIMARY KEY,
                       applied_at TEXT NOT NULL
                   )"""
            )
            versions = [
                int(row["version"])
                for row in conn.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            unknown = [version for version in versions if version > SCHEMA_VERSION]
            if unknown:
                raise RuntimeError(
                    "job-search memory schema is newer than this service: "
                    + ", ".join(map(str, unknown))
                )
            if 1 not in versions:
                self._migration_1(conn)
                conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, _now()),
                )
            expected = {
                "schema_migrations",
                "linkedin_relationships",
                "application_questions",
                "question_occurrences",
                "candidate_answers",
            }
            actual = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            missing = sorted(expected - actual)
            if missing:
                raise RuntimeError(
                    "job-search memory schema is incomplete; missing table(s): "
                    + ", ".join(missing)
                )

    @staticmethod
    def _migration_1(conn: sqlite3.Connection) -> None:
        # Keep every DDL statement inside the caller's BEGIN IMMEDIATE.
        # sqlite3.executescript() issues an implicit COMMIT and would weaken
        # the migration's atomicity.
        statements = (
            """
            CREATE TABLE linkedin_relationships (
                relationship_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                company TEXT NOT NULL,
                normalized_company TEXT NOT NULL,
                role_title TEXT NOT NULL,
                relationship_kind TEXT NOT NULL,
                linkedin_url TEXT NOT NULL,
                notes TEXT NOT NULL,
                active INTEGER NOT NULL CHECK(active IN (0, 1)),
                provenance TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX linkedin_relationship_company_idx
                ON linkedin_relationships(normalized_company, active)
            """,
            """
            CREATE TABLE application_questions (
                question_id TEXT PRIMARY KEY,
                normalized_question TEXT NOT NULL UNIQUE,
                question_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE question_occurrences (
                occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id TEXT NOT NULL REFERENCES application_questions(question_id),
                application_id TEXT NOT NULL,
                card_id TEXT NOT NULL,
                category_id TEXT NOT NULL,
                seen_at TEXT NOT NULL,
                UNIQUE(question_id, application_id)
            )
            """,
            """
            CREATE INDEX question_occurrence_category_idx
                ON question_occurrences(category_id, question_id)
            """,
            """
            CREATE TABLE candidate_answers (
                question_id TEXT NOT NULL REFERENCES application_questions(question_id),
                category_id TEXT NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(question_id, category_id)
            )
            """,
        )
        for statement in statements:
            conn.execute(statement)

    @staticmethod
    def _relationship(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["active"] = bool(result["active"])
        result.pop("normalized_company", None)
        return result

    def list_relationships(self, active: bool | None = None) -> list[dict]:
        query = "SELECT * FROM linkedin_relationships"
        params: tuple[object, ...] = ()
        if active is not None:
            query += " WHERE active = ?"
            params = (int(active),)
        query += " ORDER BY name COLLATE NOCASE, relationship_id"
        with self._connect() as conn:
            return [
                self._relationship(row)
                for row in conn.execute(query, params).fetchall()
            ]

    def put_relationship(
        self,
        relationship_id: str,
        *,
        name: str,
        company: str,
        role_title: str = "",
        relationship_kind: str = "known_contact",
        linkedin_url: str = "",
        notes: str = "",
        active: bool = True,
    ) -> tuple[str, dict]:
        relationship_id = _uuid(relationship_id)
        values = {
            "name": name.strip(),
            "company": company.strip(),
            "normalized_company": normalize_company(company),
            "role_title": role_title.strip(),
            "relationship_kind": relationship_kind.strip(),
            "linkedin_url": linkedin_url.strip(),
            "notes": notes.strip(),
            "active": int(active),
            "provenance": PROVENANCE,
        }
        if not values["name"] or not values["company"]:
            raise ValueError("relationship name and company are required")
        if not values["relationship_kind"]:
            raise ValueError("relationship kind is required")

        with self._write() as conn:
            existing = conn.execute(
                "SELECT * FROM linkedin_relationships WHERE relationship_id = ?",
                (relationship_id,),
            ).fetchone()
            if existing is not None and all(
                existing[key] == value for key, value in values.items()
            ):
                return "unchanged", self._relationship(existing)

            now = _now()
            if existing is None:
                conn.execute(
                    """INSERT INTO linkedin_relationships(
                           relationship_id, name, company, normalized_company,
                           role_title, relationship_kind, linkedin_url, notes,
                           active, provenance, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        relationship_id,
                        values["name"],
                        values["company"],
                        values["normalized_company"],
                        values["role_title"],
                        values["relationship_kind"],
                        values["linkedin_url"],
                        values["notes"],
                        values["active"],
                        values["provenance"],
                        now,
                        now,
                    ),
                )
                status = "created"
            else:
                conn.execute(
                    """UPDATE linkedin_relationships SET
                           name = ?, company = ?, normalized_company = ?,
                           role_title = ?, relationship_kind = ?, linkedin_url = ?,
                           notes = ?, active = ?, provenance = ?, updated_at = ?
                       WHERE relationship_id = ?""",
                    (
                        values["name"],
                        values["company"],
                        values["normalized_company"],
                        values["role_title"],
                        values["relationship_kind"],
                        values["linkedin_url"],
                        values["notes"],
                        values["active"],
                        values["provenance"],
                        now,
                        relationship_id,
                    ),
                )
                status = "updated"
            row = conn.execute(
                "SELECT * FROM linkedin_relationships WHERE relationship_id = ?",
                (relationship_id,),
            ).fetchone()
            assert row is not None
            return status, self._relationship(row)

    def active_relationships_for_company(self, company: str) -> list[dict]:
        normalized = normalize_company(company)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM linkedin_relationships
                   WHERE normalized_company = ? AND active = 1
                   ORDER BY name COLLATE NOCASE, relationship_id""",
                (normalized,),
            ).fetchall()
            return [self._relationship(row) for row in rows]

    @staticmethod
    def _question_summary(
        conn: sqlite3.Connection, question_id: str,
    ) -> dict:
        row = conn.execute(
            "SELECT * FROM application_questions WHERE question_id = ?",
            (question_id,),
        ).fetchone()
        if row is None:
            raise KeyError(question_id)
        occurrences = conn.execute(
            """SELECT application_id, card_id, category_id, seen_at
               FROM question_occurrences
               WHERE question_id = ?
               ORDER BY seen_at, occurrence_id""",
            (question_id,),
        ).fetchall()
        candidates = conn.execute(
            """SELECT category_id, answer, created_at, updated_at
               FROM candidate_answers
               WHERE question_id = ?
               ORDER BY category_id""",
            (question_id,),
        ).fetchall()
        return {
            "question_id": row["question_id"],
            "question": row["question_text"],
            "categories": sorted({item["category_id"] for item in occurrences}),
            "occurrence_count": len(occurrences),
            "candidate_answers": [dict(item) for item in candidates],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def record_question(
        self,
        *,
        application_id: str,
        card_id: str,
        category_id: str,
        question: str,
    ) -> tuple[str, dict, dict]:
        question_text = question.strip()
        normalized = normalize_question(question_text)
        if not normalized:
            raise ValueError("question text is required")
        with self._write() as conn:
            question_row = conn.execute(
                """SELECT * FROM application_questions
                   WHERE normalized_question = ?""",
                (normalized,),
            ).fetchone()
            now = _now()
            created_question = question_row is None
            if created_question:
                question_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO application_questions(
                           question_id, normalized_question, question_text,
                           created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (question_id, normalized, question_text, now, now),
                )
            else:
                question_id = str(question_row["question_id"])

            occurrence = conn.execute(
                """SELECT application_id, card_id, category_id, seen_at
                   FROM question_occurrences
                   WHERE question_id = ? AND application_id = ?""",
                (question_id, application_id),
            ).fetchone()
            if occurrence is None:
                conn.execute(
                    """INSERT INTO question_occurrences(
                           question_id, application_id, card_id, category_id, seen_at
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (question_id, application_id, card_id, category_id, now),
                )
                status = "created" if created_question else "recorded"
                occurrence = conn.execute(
                    """SELECT application_id, card_id, category_id, seen_at
                       FROM question_occurrences
                       WHERE question_id = ? AND application_id = ?""",
                    (question_id, application_id),
                ).fetchone()
            else:
                status = "unchanged"
            assert occurrence is not None
            return (
                status,
                self._question_summary(conn, question_id),
                dict(occurrence),
            )

    def list_questions(self, category_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if category_id is None:
                ids = [
                    str(row["question_id"])
                    for row in conn.execute(
                        """SELECT question_id FROM application_questions
                           ORDER BY created_at, question_id"""
                    )
                ]
            else:
                ids = [
                    str(row["question_id"])
                    for row in conn.execute(
                        """SELECT DISTINCT q.question_id
                           FROM application_questions q
                           LEFT JOIN question_occurrences o
                             ON o.question_id = q.question_id
                           LEFT JOIN candidate_answers c
                             ON c.question_id = q.question_id
                           WHERE o.category_id = ? OR c.category_id = ?
                           ORDER BY q.created_at, q.question_id""",
                        (category_id, category_id),
                    )
                ]
            return [self._question_summary(conn, question_id) for question_id in ids]

    def question_categories(self, question_id: str) -> set[str]:
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM application_questions WHERE question_id = ?",
                (question_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(question_id)
            return {
                str(row["category_id"])
                for row in conn.execute(
                    """SELECT DISTINCT category_id FROM question_occurrences
                       WHERE question_id = ?""",
                    (question_id,),
                )
            }

    def put_candidate_answer(
        self, question_id: str, category_id: str, answer: str,
    ) -> tuple[str, dict]:
        answer = answer.strip()
        if not answer:
            raise ValueError("candidate answer is required")
        with self._write() as conn:
            exists = conn.execute(
                "SELECT 1 FROM application_questions WHERE question_id = ?",
                (question_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(question_id)
            existing = conn.execute(
                """SELECT question_id, category_id, answer, created_at, updated_at
                   FROM candidate_answers
                   WHERE question_id = ? AND category_id = ?""",
                (question_id, category_id),
            ).fetchone()
            if existing is not None and existing["answer"] == answer:
                return "unchanged", dict(existing)
            now = _now()
            if existing is None:
                conn.execute(
                    """INSERT INTO candidate_answers(
                           question_id, category_id, answer, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (question_id, category_id, answer, now, now),
                )
                status = "created"
            else:
                conn.execute(
                    """UPDATE candidate_answers
                       SET answer = ?, updated_at = ?
                       WHERE question_id = ? AND category_id = ?""",
                    (answer, now, question_id, category_id),
                )
                status = "updated"
            row = conn.execute(
                """SELECT question_id, category_id, answer, created_at, updated_at
                   FROM candidate_answers
                   WHERE question_id = ? AND category_id = ?""",
                (question_id, category_id),
            ).fetchone()
            assert row is not None
            return status, dict(row)
