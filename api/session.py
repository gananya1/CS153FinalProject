"""
api/session.py
--------------
TutoringSession — the single entry point for a conversation.

Integrates:
  1. StandardIdentifier   — maps student messages to CCSS standard IDs
  2. StudentGraph         — reads/writes student knowledge state
  3. TutoringAgent        — generates personalized responses
  4. GraphUpdateAgent     — updates graph after each exchange

Conversation flow per turn:
  student_message →
    [1] Identify focus standard
    [2] Query StudentGraph for context
    [3] TutoringAgent → generate response
    [4] Append exchange to history
    [5] GraphUpdateAgent → analyze exchange → emit payload
    [6] StudentGraph.apply_updates(payload)

Usage
-----
    from api.session import TutoringSession

    session = TutoringSession(student_id="alex_001", grade=4)
    response = session.chat("I don't understand how to add fractions")
    print(response)

    # Continue the conversation
    response2 = session.chat("But why do I need a common denominator?")
    print(response2)

    # Inspect the student's graph
    print(session.student_graph.summary())
"""

import logging
from pathlib import Path
from typing import Optional

from agents.graph_update_agent import GraphUpdateAgent
from agents.tutoring_agent import TutoringAgent, StandardIdentifier
from graph.student_graph import StudentGraph

logger = logging.getLogger(__name__)


class TutoringSession:
    """
    Stateful conversation session for one student.

    Manages the full agent pipeline and conversation history.
    Can be persisted/resumed since all state lives in SQLite.
    """

    def __init__(
        self,
        student_id: str,
        grade: Optional[int] = None,
        student_name: Optional[str] = None,
        db_dir: Optional[Path] = None,
        update_graph_after_n_turns: int = 1,  # how often to run the graph update agent
    ):
        self.student_id = student_id
        self.grade = grade
        self.student_name = student_name or student_id
        self.update_graph_after_n_turns = update_graph_after_n_turns

        # Agents
        self.identifier = StandardIdentifier()
        self.tutor = TutoringAgent()
        self.graph_update_agent = GraphUpdateAgent()

        # Student graph
        kwargs = {}
        if db_dir:
            kwargs["db_dir"] = db_dir
        self.student_graph = StudentGraph(
            student_id=student_id,
            grade=grade,
            **kwargs,
        )

        # Conversation history (list of {"role": ..., "content": ...})
        # We store the raw student messages (not the context-injected versions)
        # so history is readable and replayable.
        self._history: list[dict] = []

        # Track turns for batched graph updates
        self._turns_since_update: int = 0
        self._pending_exchanges: list[dict] = []

        logger.info("TutoringSession started for student '%s' (grade %s)", student_id, grade)

    # ------------------------------------------------------------------
    # Main chat interface
    # ------------------------------------------------------------------

    def chat(self, student_message: str) -> str:
        """
        Process one student message and return the tutor's response.

        Also updates the student knowledge graph based on the exchange.
        """
        # Step 1: Identify which CCSS standard the student is asking about
        focus_standard = self.identifier.identify(student_message, grade=self.grade)
        logger.info("Focus standard identified: %s", focus_standard)

        # Step 2: Query student graph for context
        if focus_standard and focus_standard in self.student_graph._cg.nodes:
            context = self.student_graph.get_context_for_tutor(focus_standard)
        else:
            # No specific standard identified — provide minimal context
            context = {
                "standard_id": focus_standard or "unknown",
                "standard_info": {"description": "", "grade": str(self.grade or ""), "domain": "", "cluster": ""},
                "student_state": None,
                "prerequisites": [],
                "unmastered_prereqs": [],
                "dependents": [],
                "misconceptions": [],
                "confusions": [],
                "related": [],
            }
            logger.debug("No known standard identified — using minimal context")

        # Step 3: Build history for tutor (raw messages only, not context-injected)
        # We pass history as simple role/content pairs; the context is injected
        # only into the current turn by TutoringAgent.respond()
        tutor_history = self._build_tutor_history()

        # Step 4: Generate tutor response
        response = self.tutor.respond(
            student_message=student_message,
            knowledge_context=context,
            history=tutor_history,
            student_name=self.student_name,
        )

        # Step 5: Append to history
        self._history.append({"role": "user", "content": student_message})
        self._history.append({"role": "assistant", "content": response})

        # Track this exchange for graph update
        self._pending_exchanges.append({"role": "user", "content": student_message})
        self._pending_exchanges.append({"role": "assistant", "content": response})
        self._turns_since_update += 1

        # Step 6: Run graph update agent (every N turns)
        if self._turns_since_update >= self.update_graph_after_n_turns:
            self._run_graph_update(focus_standard)

        return response

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_student_summary(self) -> dict:
        """Return a summary of the student's knowledge graph state."""
        return self.student_graph.summary()

    def get_focus_context(self, standard_id: str) -> dict:
        """Return the full tutor context for a standard (for debugging/display)."""
        return self.student_graph.get_context_for_tutor(standard_id)

    def history(self) -> list[dict]:
        """Return the full conversation history."""
        return list(self._history)

    def flush_graph_update(self) -> None:
        """Force a graph update immediately (useful at end of session)."""
        if self._pending_exchanges:
            self._run_graph_update(focus_standard=None)

    def close(self) -> None:
        """Flush any pending updates and close the database connection."""
        self.flush_graph_update()
        self.student_graph.close()
        logger.info("Session closed for student '%s'", self.student_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_graph_update(self, focus_standard: Optional[str]) -> None:
        """Run the Graph Update Agent on pending exchanges and apply the payload."""
        if not self._pending_exchanges:
            return

        logger.info(
            "Running Graph Update Agent on %d messages (focus: %s)",
            len(self._pending_exchanges),
            focus_standard,
        )
        payload = self.graph_update_agent.analyze(
            conversation=self._pending_exchanges,
            focus_standard=focus_standard,
            grade=self.grade,
        )

        if payload.updates or payload.confusions:
            self.student_graph.apply_updates(payload)

        if payload.inferred_standards:
            self.student_graph.mark_seen(payload.inferred_standards)

        # Reset pending buffer
        self._pending_exchanges = []
        self._turns_since_update = 0

    def _build_tutor_history(self) -> list[dict]:
        """
        Build the history list to pass to the tutor.
        Returns all prior turns as simple role/content pairs.
        The tutor will see context injected only for the CURRENT turn.
        """
        return list(self._history)
