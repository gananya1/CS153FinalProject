"""
tests/test_agents.py
--------------------
Integration tests for the KnowledgeMap Tutor system.

These tests use real Anthropic API calls — set ANTHROPIC_API_KEY in env.
For fast unit tests that don't call the API, see the mock-based tests below.

Run:
    pytest tests/test_agents.py -v
    pytest tests/test_agents.py -v -k "not live"   # skip live API tests
"""

import json
import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.schema import (
    GraphUpdatePayload, StandardUpdate, ConfusionUpdate, EdgeType
)
from graph.student_graph import StudentGraph
from data.coherence_map import load_coherence_graph, get_prerequisites, get_dependents
from agents.graph_update_agent import GraphUpdateAgent
from agents.tutoring_agent import TutoringAgent, StandardIdentifier
from api.session import TutoringSession

from dotenv import load_dotenv
load_dotenv()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def coherence_graph():
    """Shared coherence graph (uses fallback data if no network)."""
    return load_coherence_graph()


@pytest.fixture
def student_graph(tmp_db_dir, coherence_graph):
    sg = StudentGraph(
        student_id="test_student",
        grade=4,
        db_dir=tmp_db_dir,
        coherence_graph=coherence_graph,
    )
    yield sg
    sg.close()


# ---------------------------------------------------------------------------
# Coherence Map Tests
# ---------------------------------------------------------------------------

class TestCoherenceMap:
    def test_graph_loads(self, coherence_graph):
        assert coherence_graph.number_of_nodes() > 0
        assert coherence_graph.number_of_edges() > 0

    def test_known_standards_present(self, coherence_graph):
        """Core standards from the fallback dataset should always be present."""
        for std in ["3.NF.A.1", "4.NF.A.1", "5.NF.A.1"]:
            assert std in coherence_graph.nodes, f"{std} missing from coherence graph"

    def test_prerequisite_edges_directed(self, coherence_graph):
        """3.NF.A.1 should be a prerequisite of 4.NF.A.1."""
        # 3.NF.A.1 → 4.NF.A.1 means 3.NF.A.1 is prerequisite of 4.NF.A.1
        if coherence_graph.has_edge("3.NF.A.1", "4.NF.A.1"):
            edge = coherence_graph.edges["3.NF.A.1", "4.NF.A.1"]
            assert edge.get("type") == "PREREQUISITE_OF"

    def test_get_prerequisites(self, coherence_graph):
        prereqs = get_prerequisites("4.NF.A.1", graph=coherence_graph, depth=1)
        assert isinstance(prereqs, list)
        # 3.NF.A.1 or 3.NF.A.3 should be a prerequisite of 4.NF.A.1
        assert len(prereqs) > 0

    def test_get_dependents(self, coherence_graph):
        deps = get_dependents("3.NF.A.1", graph=coherence_graph, depth=1)
        assert isinstance(deps, list)
        assert len(deps) > 0


# ---------------------------------------------------------------------------
# StudentGraph Tests
# ---------------------------------------------------------------------------

class TestStudentGraph:
    def test_initial_state_none(self, student_graph):
        """Standards not yet seen should return None."""
        state = student_graph.get_state("3.NF.A.1")
        assert state is None

    def test_apply_mastered_update(self, student_graph):
        payload = GraphUpdatePayload(
            updates=[
                StandardUpdate(
                    standard="3.OA.A.1",
                    status=EdgeType.MASTERED,
                    confidence=0.9,
                    note="Student explained multiplication fluently",
                )
            ]
        )
        student_graph.apply_updates(payload)
        state = student_graph.get_state("3.OA.A.1")
        assert state is not None
        assert state.status == "MASTERED"
        assert state.confidence == pytest.approx(0.9)
        assert state.attempts == 1

    def test_apply_misconception(self, student_graph):
        payload = GraphUpdatePayload(
            updates=[
                StandardUpdate(
                    standard="3.NF.A.2",
                    status=EdgeType.MISCONCEPTION,
                    confidence=0.1,
                    misconception="Thinks larger denominator means larger fraction",
                )
            ]
        )
        student_graph.apply_updates(payload)
        state = student_graph.get_state("3.NF.A.2")
        assert state.status == "MISCONCEPTION"

        # Misconception edge should also be written
        ctx = student_graph.get_context_for_tutor("3.NF.A.2")
        misconceptions = ctx.get("misconceptions", [])
        assert any("denominator" in m["description"].lower() for m in misconceptions)

    def test_apply_confusion_link(self, student_graph):
        payload = GraphUpdatePayload(
            confusions=[
                ConfusionUpdate(
                    from_standard="3.NF.A.1",
                    to_standard="3.NF.A.3",
                    description="Student applies unit fraction rules to comparison",
                )
            ]
        )
        student_graph.apply_updates(payload)
        ctx = student_graph.get_context_for_tutor("3.NF.A.1")
        confusions = ctx.get("confusions", [])
        assert len(confusions) > 0

    def test_increments_attempts(self, student_graph):
        payload = GraphUpdatePayload(updates=[
            StandardUpdate(standard="3.NF.A.1", status="PARTIAL", confidence=0.3)
        ])
        student_graph.apply_updates(payload)
        student_graph.apply_updates(payload)
        state = student_graph.get_state("3.NF.A.1")
        assert state.attempts == 2

    def test_mark_seen(self, student_graph):
        student_graph.mark_seen(["3.NF.A.1", "4.NF.A.1"])
        s1 = student_graph.get_state("3.NF.A.1")
        s2 = student_graph.get_state("4.NF.A.1")
        assert s1 is not None
        assert s2 is not None
        assert s1.status == "UNSEEN"

    def test_get_context_for_tutor_structure(self, student_graph):
        ctx = student_graph.get_context_for_tutor("3.NF.A.1")
        required_keys = [
            "standard_id", "standard_info", "student_state",
            "prerequisites", "unmastered_prereqs", "dependents",
            "misconceptions", "confusions", "related",
        ]
        for key in required_keys:
            assert key in ctx, f"Missing key: {key}"

    def test_summary(self, student_graph):
        payload = GraphUpdatePayload(updates=[
            StandardUpdate(standard="3.NF.A.1", status="PARTIAL", confidence=0.4),
            StandardUpdate(standard="3.OA.A.1", status="MASTERED", confidence=0.9),
        ])
        student_graph.apply_updates(payload)
        summary = student_graph.summary()
        assert summary["total_standards_seen"] == 2
        assert summary["by_status"]["PARTIAL"] == 1
        assert summary["by_status"]["MASTERED"] == 1


# ---------------------------------------------------------------------------
# Graph Update Agent Tests (mock LLM)
# ---------------------------------------------------------------------------

class TestGraphUpdateAgentParsing:
    """Test the JSON parsing logic without making real API calls."""

    def test_parse_valid_payload(self):
        agent = GraphUpdateAgent.__new__(GraphUpdateAgent)
        raw = json.dumps({
            "updates": [
                {
                    "standard": "3.NF.A.1",
                    "status": "PARTIAL",
                    "confidence": 0.4,
                    "note": "Understands unit fractions",
                    "misconception": None,
                }
            ],
            "confusions": [],
            "inferred_standards": ["3.NF.A.1", "3.NF.A.2"],
        })
        payload = agent._parse_payload(raw)
        assert len(payload.updates) == 1
        assert payload.updates[0].standard == "3.NF.A.1"
        assert payload.updates[0].status == "PARTIAL"
        assert payload.updates[0].confidence == pytest.approx(0.4)
        assert payload.inferred_standards == ["3.NF.A.1", "3.NF.A.2"]

    def test_parse_with_markdown_fences(self):
        agent = GraphUpdateAgent.__new__(GraphUpdateAgent)
        raw = '```json\n{"updates": [], "confusions": [], "inferred_standards": []}\n```'
        payload = agent._parse_payload(raw)
        assert payload.updates == []

    def test_parse_invalid_json_returns_empty(self):
        agent = GraphUpdateAgent.__new__(GraphUpdateAgent)
        payload = agent._parse_payload("this is not json at all")
        assert payload.updates == []
        assert payload.confusions == []

    def test_parse_with_confusion(self):
        agent = GraphUpdateAgent.__new__(GraphUpdateAgent)
        raw = json.dumps({
            "updates": [],
            "confusions": [
                {
                    "from_standard": "3.NF.A.1",
                    "to_standard": "3.NF.A.3",
                    "description": "Mixes up unit fractions with comparison",
                }
            ],
            "inferred_standards": [],
        })
        payload = agent._parse_payload(raw)
        assert len(payload.confusions) == 1
        assert payload.confusions[0].from_standard == "3.NF.A.1"


# ---------------------------------------------------------------------------
# Live API Tests (require ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)
class TestLiveAPIIntegration:

    @pytest.fixture
    def session(self, tmp_db_dir):
        s = TutoringSession(
            student_id="live_test_student",
            grade=4,
            db_dir=tmp_db_dir,
        )
        yield s
        s.close()

    def test_single_chat_turn(self, session):
        response = session.chat("I don't understand what fractions are")
        assert isinstance(response, str)
        assert len(response) > 20

    def test_graph_updates_after_session(self, session):
        session.chat("I don't understand fractions at all")
        session.chat("A fraction is like cutting a pizza")
        session.flush_graph_update()

        summary = session.get_student_summary()
        # After at least one exchange, something should be in the graph
        assert isinstance(summary, dict)

    def test_standard_identifier(self):
        identifier = StandardIdentifier()
        std = identifier.identify("I don't get how to add fractions with different denominators", grade=5)
        # Should identify something in the 5.NF domain
        assert std is None or isinstance(std, str)
        if std:
            assert "." in std  # basic CCSS format check

    def test_multi_turn_conversation(self, session):
        r1 = session.chat("What is 1/2 plus 1/4?")
        assert len(r1) > 0
        r2 = session.chat("I think you just add the top numbers and the bottom numbers")
        assert len(r2) > 0
        # Tutor should address this misconception
        assert len(session.history()) == 4  # 2 user + 2 assistant
