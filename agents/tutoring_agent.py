"""
agents/tutoring_agent.py
------------------------
The Tutoring Agent.

Responsibility: given the student's message, their conversation history,
and their current knowledge graph context, generate a personalized tutoring
response that:
  - Addresses prerequisite gaps before the surface question
  - Surfaces and corrects misconceptions directly
  - Meets the student's actual level, not their nominal grade
  - Ends with a question or practice prompt

Usage
-----
    from agents.tutoring_agent import TutoringAgent
    from agents.standard_identifier import StandardIdentifier
    from graph.student_graph import StudentGraph

    tutor = TutoringAgent()
    identifier = StandardIdentifier()

    # Identify what standard the student is asking about
    standard_id = identifier.identify(student_message, grade=4)

    # Pull context from the student graph
    context = student_graph.get_context_for_tutor(standard_id)

    # Generate response
    response = tutor.respond(
        student_message=student_message,
        knowledge_context=context,
        history=conversation_history,
    )
"""

import json
import logging
from typing import Optional

import anthropic

from agents.prompts import (
    TUTOR_SYSTEM,
    TUTOR_USER_TEMPLATE,
    STANDARD_IDENTIFIER_SYSTEM,
    STANDARD_IDENTIFIER_USER_TEMPLATE,
)
from graph.schema import StudentStandardState

logger = logging.getLogger(__name__)

TUTOR_MODEL = "claude-sonnet-4-6"
IDENTIFIER_MODEL = "claude-haiku-4-5-20251001"


def _format_knowledge_context(context: dict) -> str:
    """
    Render the knowledge context dict into a clean, structured string
    for injection into the tutor's prompt.
    """
    parts = []

    std = context.get("standard_id", "unknown")
    info = context.get("standard_info", {})
    parts.append(f"FOCUS STANDARD: {std}")
    parts.append(f"  Description: {info.get('description', 'N/A')}")
    parts.append(f"  Grade: {info.get('grade', '?')}  Domain: {info.get('domain', '?')}")

    # Student state on this standard
    state: Optional[StudentStandardState] = context.get("student_state")
    if state is None:
        parts.append("\nSTUDENT STATE ON THIS STANDARD: Not yet encountered")
    else:
        parts.append(f"\nSTUDENT STATE ON THIS STANDARD:")
        parts.append(f"  Status: {state.status}")
        parts.append(f"  Confidence: {state.confidence:.2f}")
        parts.append(f"  Attempts: {state.attempts}")
        if state.student_explanation:
            parts.append(f"  Student's own explanation: \"{state.student_explanation}\"")
        if state.notes:
            recent = state.notes[-3:]  # last 3 observations
            parts.append(f"  Recent observations:")
            for note in recent:
                parts.append(f"    - {note}")

    # Unmastered prerequisites (most important for pedagogy)
    unmastered = context.get("unmastered_prereqs", [])
    if unmastered:
        parts.append(f"\nUNMASTERED PREREQUISITES ({len(unmastered)}):")
        for p in unmastered[:5]:  # cap at 5
            pstate = p.get("student_state")
            status_str = pstate.status if pstate else "UNSEEN"
            conf_str = f" (confidence: {pstate.confidence:.2f})" if pstate else ""
            parts.append(f"  • {p['standard_id']} [{status_str}{conf_str}]")
            desc = p.get("description", "")
            if desc:
                parts.append(f"    {desc[:120]}")
    else:
        parts.append("\nUNMASTERED PREREQUISITES: None — prerequisite chain appears solid")

    # Active misconceptions
    misconceptions = context.get("misconceptions", [])
    if misconceptions:
        parts.append(f"\nACTIVE MISCONCEPTIONS:")
        for m in misconceptions:
            parts.append(f"  ⚠ {m['standard_id']}: {m['description']}")

    # Confusion links
    confusions = context.get("confusions", [])
    if confusions:
        parts.append(f"\nCONFUSION LINKS:")
        for c in confusions:
            parts.append(f"  ⚠ {c['from']} ↔ {c['to']}: {c['description']}")

    # What this standard unlocks
    dependents = context.get("dependents", [])
    if dependents:
        parts.append(f"\nSTANDARDS THIS UNLOCKS: {', '.join(dependents[:6])}")

    return "\n".join(parts)


class StandardIdentifier:
    """
    Lightweight agent that maps a student's free-text message to CCSS standard IDs.
    Uses a fast model since this runs before every tutor response.
    """

    def __init__(self, model: str = IDENTIFIER_MODEL):
        self.client = anthropic.Anthropic()
        self.model = model

    def identify(self, message: str, grade: Optional[int] = None) -> Optional[str]:
        """
        Return the primary CCSS standard ID for a student message, or None.

        Parameters
        ----------
        message : student's message
        grade   : student's grade level (helps narrow down standards)
        """
        grade_str = str(grade) if grade else "unknown"
        user_content = STANDARD_IDENTIFIER_USER_TEMPLATE.format(
            grade=grade_str,
            message=message,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                system=STANDARD_IDENTIFIER_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = response.content[0].text.strip()
            # Strip fences
            if raw.startswith("```"):
                raw = "\n".join(
                    l for l in raw.split("\n") if not l.startswith("```")
                ).strip()
            data = json.loads(raw)
            primary = data.get("primary_standard")
            logger.debug("Identified standard: %s for message: %s", primary, message[:60])
            return primary
        except Exception as e:
            logger.warning("StandardIdentifier failed: %s", e)
            return None


class TutoringAgent:
    """
    Generates personalized tutoring responses using the student's knowledge context.

    Each call to `respond()` makes one LLM call (Sonnet — higher quality needed here).
    The conversation history is passed as the messages array for multi-turn coherence.
    """

    def __init__(self, model: str = TUTOR_MODEL):
        self.client = anthropic.Anthropic()
        self.model = model

    def respond(
        self,
        student_message: str,
        knowledge_context: dict,
        history: list[dict],
        student_name: Optional[str] = None,
    ) -> str:
        """
        Generate a tutoring response.

        Parameters
        ----------
        student_message    : the student's current message
        knowledge_context  : dict from StudentGraph.get_context_for_tutor()
        history            : list of prior {"role": ..., "content": ...} messages
                             (NOT including the current student_message)
        student_name       : optional, used for personalization

        Returns
        -------
        str — the tutor's response text
        """
        context_str = _format_knowledge_context(knowledge_context)

        # Build the user turn: context block + student message
        user_turn_content = TUTOR_USER_TEMPLATE.format(
            knowledge_context=context_str,
            student_message=student_message,
        )

        # Build messages: full history + current user turn
        messages = list(history) + [{"role": "user", "content": user_turn_content}]

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=TUTOR_SYSTEM,
                messages=messages,
            )
            reply = response.content[0].text.strip()
            logger.debug("Tutor response (%d chars)", len(reply))
            return reply

        except Exception as e:
            logger.error("TutoringAgent error: %s", e)
            return (
                "I'm having a bit of trouble right now — could you try rephrasing "
                "your question? I want to make sure I help you properly."
            )
