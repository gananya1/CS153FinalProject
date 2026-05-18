"""
graph/student_graph.py
----------------------
The Student Knowledge Graph (SKG).

Each student has their own SQLite database storing:
  - node attributes  (status, confidence, attempts, notes, …)
  - student-specific edges  (MISCONCEPTION, CONFUSES_WITH, …)

Structural edges (PREREQUISITE_OF, RELATED_TO) come from the shared
Coherence Map graph and are merged in at query time.

Public API
----------
StudentGraph(student_id, grade, db_dir)
    .get_state(standard_id)            → StudentStandardState | None
    .get_context_for_tutor(standard_id) → dict  (everything the tutor needs)
    .apply_updates(payload)            → None
    .mark_seen(standard_ids)           → None
    .all_states()                      → list[StudentStandardState]
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import networkx as nx

from data.coherence_map import load_coherence_graph, get_prerequisites, get_dependents
from graph.schema import (
    EdgeType,
    StudentStandardState,
    GraphUpdatePayload,
    StandardUpdate,
    ConfusionUpdate,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_DIR = Path(__file__).parent.parent / "data" / "students"


class StudentGraph:
    """
    Per-student knowledge graph backed by SQLite.

    The underlying coherence map graph is loaded once and shared;
    student-specific state lives in a SQLite db at:
        <db_dir>/<student_id>.db
    """

    def __init__(
        self,
        student_id: str,
        grade: Optional[int] = None,
        db_dir: Path = DEFAULT_DB_DIR,
        coherence_graph: Optional[nx.DiGraph] = None,
    ):
        self.student_id = student_id
        self.grade = grade
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / f"{student_id}.db"

        # Shared structural graph (loaded once per process)
        self._cg: nx.DiGraph = coherence_graph or load_coherence_graph()

        self._conn = self._init_db()

    # ------------------------------------------------------------------
    # DB setup
    # ------------------------------------------------------------------

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS standard_states (
                standard_id     TEXT PRIMARY KEY,
                status          TEXT NOT NULL DEFAULT 'UNSEEN',
                confidence      REAL NOT NULL DEFAULT 0.0,
                attempts        INTEGER NOT NULL DEFAULT 0,
                last_seen       TEXT,
                student_explanation TEXT,
                notes           TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS student_edges (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                from_node       TEXT NOT NULL,
                to_node         TEXT NOT NULL,
                edge_type       TEXT NOT NULL,
                description     TEXT,
                created_at      TEXT NOT NULL,
                UNIQUE(from_node, to_node, edge_type)
            );
        """)
        conn.commit()
        return conn

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_state(self, standard_id: str) -> Optional[StudentStandardState]:
        """Return the student's current state for a standard, or None if unseen."""
        row = self._conn.execute(
            "SELECT * FROM standard_states WHERE standard_id = ?", (standard_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_state(row)

    def get_context_for_tutor(self, standard_id: str) -> dict:
        """
        Assemble everything the Tutoring Agent needs before responding.

        Returns a dict with:
          - standard_info      : description from coherence map
          - student_state      : StudentStandardState (or None)
          - prerequisites      : list of {standard_id, description, student_state}
          - unmastered_prereqs : subset of prerequisites not yet mastered
          - dependents         : standards this one unlocks
          - misconceptions     : list of {standard_id, description}
          - confusions         : list of {from, to, description}
          - related            : list of related standard IDs
        """
        node_data = self._cg.nodes.get(standard_id, {})
        student_state = self.get_state(standard_id)

        # Prerequisites (up to 2 hops)
        prereq_ids = get_prerequisites(standard_id, graph=self._cg, depth=2)
        prerequisites = []
        unmastered_prereqs = []
        for pid in prereq_ids:
            pstate = self.get_state(pid)
            pinfo = self._cg.nodes.get(pid, {})
            entry = {
                "standard_id": pid,
                "description": pinfo.get("description", ""),
                "student_state": pstate,
            }
            prerequisites.append(entry)
            if pstate is None or pstate.status not in ("MASTERED",):
                unmastered_prereqs.append(entry)

        # Dependents (1 hop — what this unlocks)
        dependent_ids = get_dependents(standard_id, graph=self._cg, depth=1)

        # Misconceptions on this standard
        misconception_rows = self._conn.execute(
            """SELECT from_node, to_node, description FROM student_edges
               WHERE to_node = ? AND edge_type = ?""",
            (standard_id, EdgeType.MISCONCEPTION),
        ).fetchall()
        misconceptions = [
            {"standard_id": r["to_node"], "description": r["description"]}
            for r in misconception_rows
        ]

        # Confusion links involving this standard
        confusion_rows = self._conn.execute(
            """SELECT from_node, to_node, description FROM student_edges
               WHERE (from_node = ? OR to_node = ?) AND edge_type = ?""",
            (standard_id, standard_id, EdgeType.CONFUSES_WITH),
        ).fetchall()
        confusions = [
            {"from": r["from_node"], "to": r["to_node"], "description": r["description"]}
            for r in confusion_rows
        ]

        # Related standards
        related = [
            nbr for nbr in self._cg.neighbors(standard_id)
            if self._cg.edges[standard_id, nbr].get("type") == "RELATED_TO"
        ]

        return {
            "standard_id": standard_id,
            "standard_info": {
                "description": node_data.get("description", ""),
                "grade": node_data.get("grade", ""),
                "domain": node_data.get("domain", ""),
                "cluster": node_data.get("cluster", ""),
            },
            "student_state": student_state,
            "prerequisites": prerequisites,
            "unmastered_prereqs": unmastered_prereqs,
            "dependents": dependent_ids,
            "misconceptions": misconceptions,
            "confusions": confusions,
            "related": related,
        }

    def all_states(self) -> list[StudentStandardState]:
        rows = self._conn.execute("SELECT * FROM standard_states").fetchall()
        return [self._row_to_state(r) for r in rows]

    def summary(self) -> dict:
        """High-level stats for display / debugging."""
        rows = self.all_states()
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        return {
            "student_id": self.student_id,
            "total_standards_seen": len(rows),
            "by_status": by_status,
        }

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def apply_updates(self, payload: GraphUpdatePayload) -> None:
        """Apply a GraphUpdatePayload from the Graph Update Agent to the DB."""
        now = datetime.now(timezone.utc).isoformat()

        with self._conn:
            for upd in payload.updates:
                self._apply_standard_update(upd, now)
            for conf in payload.confusions:
                self._apply_confusion(conf, now)

        logger.info(
            "[%s] Applied %d standard updates, %d confusion links",
            self.student_id,
            len(payload.updates),
            len(payload.confusions),
        )

    def mark_seen(self, standard_ids: list[str]) -> None:
        """Record that a standard was touched in conversation (without a full state update)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn:
            for sid in standard_ids:
                existing = self._conn.execute(
                    "SELECT standard_id FROM standard_states WHERE standard_id = ?", (sid,)
                ).fetchone()
                if existing is None:
                    self._conn.execute(
                        """INSERT INTO standard_states (standard_id, status, last_seen)
                           VALUES (?, 'UNSEEN', ?)""",
                        (sid, now),
                    )
                else:
                    self._conn.execute(
                        "UPDATE standard_states SET last_seen = ? WHERE standard_id = ?",
                        (now, sid),
                    )

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_standard_update(self, upd: StandardUpdate, now: str) -> None:
        existing = self._conn.execute(
            "SELECT * FROM standard_states WHERE standard_id = ?", (upd.standard,)
        ).fetchone()

        if existing is None:
            # Insert new row
            notes = json.dumps([upd.note] if upd.note else [])
            self._conn.execute(
                """INSERT INTO standard_states
                   (standard_id, status, confidence, attempts, last_seen, notes)
                   VALUES (?, ?, ?, 1, ?, ?)""",
                (
                    upd.standard,
                    upd.status or "UNSEEN",
                    upd.confidence if upd.confidence is not None else 0.0,
                    now,
                    notes,
                ),
            )
        else:
            # Update existing row
            notes = json.loads(existing["notes"])
            if upd.note:
                notes.append(f"[{now[:10]}] {upd.note}")

            new_status = upd.status if upd.status is not None else existing["status"]
            new_confidence = (
                upd.confidence if upd.confidence is not None else existing["confidence"]
            )
            self._conn.execute(
                """UPDATE standard_states
                   SET status = ?, confidence = ?, attempts = attempts + 1,
                       last_seen = ?, notes = ?
                   WHERE standard_id = ?""",
                (
                    new_status,
                    new_confidence,
                    now,
                    json.dumps(notes),
                    upd.standard,
                ),
            )

        # If it's a misconception, also write a student edge
        if upd.status == EdgeType.MISCONCEPTION and upd.misconception:
            self._conn.execute(
                """INSERT OR REPLACE INTO student_edges
                   (from_node, to_node, edge_type, description, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    self.student_id,
                    upd.standard,
                    EdgeType.MISCONCEPTION,
                    upd.misconception,
                    now,
                ),
            )

    def _apply_confusion(self, conf: ConfusionUpdate, now: str) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO student_edges
               (from_node, to_node, edge_type, description, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                conf.from_standard,
                conf.to_standard,
                EdgeType.CONFUSES_WITH,
                conf.description,
                now,
            ),
        )

    @staticmethod
    def _row_to_state(row: sqlite3.Row) -> StudentStandardState:
        return StudentStandardState(
            standard_id=row["standard_id"],
            status=row["status"],
            confidence=row["confidence"],
            attempts=row["attempts"],
            last_seen=row["last_seen"],
            student_explanation=row["student_explanation"],
            notes=json.loads(row["notes"]),
        )
