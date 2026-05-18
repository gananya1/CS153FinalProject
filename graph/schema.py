"""
graph/schema.py
---------------
Type definitions for the Student Knowledge Graph.

Node types  : Standard (one per CCSS standard, shared scaffold)
              Student   (one per student, owns SKG state)

Edge types  (stored as NetworkX edge attribute `type`):

  Structural edges — from Coherence Map, same for all students:
    PREREQUISITE_OF   directed  A → B  "can't do B without A"
    RELATED_TO        undirected         "related but not strictly prerequisite"

  Student-state edges — per-student, written by the Graph Update Agent:
    MASTERED          student → standard  solid understanding demonstrated
    PARTIAL           student → standard  emerging, has gaps
    STRUGGLES_WITH    student → standard  repeated attempts, not converging
    MISCONCEPTION     student → standard  specific wrong belief (carries `description`)
    CONFUSES_WITH     standard → standard per-student cross-standard confusion link
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Edge type constants (keep as plain strings for easy JSON serialisation)
# ---------------------------------------------------------------------------

class EdgeType:
    # Structural (Coherence Map)
    PREREQUISITE_OF = "PREREQUISITE_OF"
    RELATED_TO = "RELATED_TO"

    # Student state
    MASTERED = "MASTERED"
    PARTIAL = "PARTIAL"
    STRUGGLES_WITH = "STRUGGLES_WITH"
    MISCONCEPTION = "MISCONCEPTION"
    CONFUSES_WITH = "CONFUSES_WITH"

    STUDENT_STATE_TYPES = {MASTERED, PARTIAL, STRUGGLES_WITH, MISCONCEPTION, CONFUSES_WITH}


# ---------------------------------------------------------------------------
# Node data models
# ---------------------------------------------------------------------------

@dataclass
class StandardNode:
    """A CCSS standard — shared scaffold, not per-student."""
    standard_id: str          # e.g. "3.NF.A.1"
    grade: str                # e.g. "3", "K", "HS"
    domain: str               # e.g. "NF" (Number and Fractions)
    cluster: str              # e.g. "A" – cluster letter
    description: str          # Full standard text
    is_major: bool = False    # Major Work of the Grade


@dataclass
class StudentStandardState:
    """
    Per-student state for a single CCSS standard.
    Stored as node attributes on the student's subgraph view.
    """
    standard_id: str
    status: str = "UNSEEN"         # UNSEEN | PARTIAL | MASTERED | STRUGGLES_WITH
    confidence: float = 0.0        # 0.0 – 1.0
    attempts: int = 0
    last_seen: Optional[str] = None          # ISO date string
    student_explanation: Optional[str] = None  # student's own words
    notes: list = field(default_factory=list)  # running list of agent observations


# ---------------------------------------------------------------------------
# Graph update payload (emitted by the Graph Update Agent)
# ---------------------------------------------------------------------------

@dataclass
class StandardUpdate:
    """A single node update emitted by the Graph Update Agent."""
    standard: str                     # CCSS standard ID
    status: Optional[str] = None      # new EdgeType student-state value
    confidence: Optional[float] = None
    note: Optional[str] = None        # observation to append to notes list
    misconception: Optional[str] = None  # if status == MISCONCEPTION


@dataclass
class ConfusionUpdate:
    """A cross-standard confusion link to add."""
    from_standard: str
    to_standard: str
    description: str


@dataclass
class GraphUpdatePayload:
    """Full payload returned by the Graph Update Agent."""
    updates: list[StandardUpdate] = field(default_factory=list)
    confusions: list[ConfusionUpdate] = field(default_factory=list)
    inferred_standards: list[str] = field(default_factory=list)  # standards the convo touched
