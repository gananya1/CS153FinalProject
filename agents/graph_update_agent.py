"""
agents/graph_update_agent.py
-----------------------------
The Graph Update Agent.

Responsibility: given a tutoring conversation, emit a structured
GraphUpdatePayload describing what was learned about the student's
knowledge state. This payload is then applied to the StudentGraph.

The agent is stateless — it receives the full conversation and returns
a payload. Persistence is handled by StudentGraph.apply_updates().

Usage
-----
    from agents.graph_update_agent import GraphUpdateAgent
    from graph.student_graph import StudentGraph

    agent = GraphUpdateAgent()
    payload = agent.analyze(conversation_history, focus_standard="3.NF.A.1")
    student_graph.apply_updates(payload)
"""

import json
import logging
from typing import Optional

import anthropic

from agents.prompts import (
    GRAPH_UPDATE_SYSTEM,
    GRAPH_UPDATE_USER_TEMPLATE,
)
from graph.schema import (
    GraphUpdatePayload,
    StandardUpdate,
    ConfusionUpdate,
)

logger = logging.getLogger(__name__)

# Model to use for the update agent (lightweight — this runs after every turn)
UPDATE_MODEL = "claude-haiku-4-5-20251001"
# Fall back to Sonnet if Haiku unavailable in your tier
FALLBACK_MODEL = "claude-sonnet-4-6"


def _format_conversation(messages: list[dict]) -> str:
    """Format conversation history into a readable string for the prompt."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown").capitalize()
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


class GraphUpdateAgent:
    """
    Analyzes tutoring conversations and emits structured knowledge graph updates.

    Each call to `analyze()` makes one LLM call (to a fast, cheap model)
    and returns a GraphUpdatePayload ready to be applied to the StudentGraph.
    """

    def __init__(self, model: str = UPDATE_MODEL):
        self.client = anthropic.Anthropic()
        self.model = model

    def analyze(
        self,
        conversation: list[dict],
        focus_standard: Optional[str] = None,
        grade: Optional[int] = None,
    ) -> GraphUpdatePayload:
        """
        Analyze a conversation and return a GraphUpdatePayload.

        Parameters
        ----------
        conversation   : list of {"role": "user"|"assistant", "content": str}
        focus_standard : CCSS standard ID the session was focused on (if known)
        grade          : student's grade level (1-8)

        Returns
        -------
        GraphUpdatePayload — safe to apply even if empty (no updates)
        """
        if not conversation:
            logger.debug("Empty conversation — returning empty payload")
            return GraphUpdatePayload()

        conversation_text = _format_conversation(conversation)
        focus_str = focus_standard or "unknown (infer from conversation)"

        user_content = GRAPH_UPDATE_USER_TEMPLATE.format(
            conversation=conversation_text,
            focus_standard=focus_str,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=GRAPH_UPDATE_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
            )
            raw_text = response.content[0].text.strip()
            logger.debug("Graph Update Agent raw response:\n%s", raw_text)
            return self._parse_payload(raw_text)

        except anthropic.APIStatusError as e:
            if e.status_code == 404 and self.model != FALLBACK_MODEL:
                logger.warning("Model %s unavailable, falling back to %s", self.model, FALLBACK_MODEL)
                self.model = FALLBACK_MODEL
                return self.analyze(conversation, focus_standard, grade)
            logger.error("Anthropic API error in Graph Update Agent: %s", e)
            return GraphUpdatePayload()
        except Exception as e:
            logger.error("Unexpected error in Graph Update Agent: %s", e)
            return GraphUpdatePayload()

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse_payload(self, raw_text: str) -> GraphUpdatePayload:
        """Parse the LLM's JSON output into a GraphUpdatePayload."""
        # Strip any accidental markdown fences
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(
                line for line in lines
                if not line.startswith("```")
            ).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse Graph Update Agent JSON: %s\nRaw: %s", e, raw_text)
            return GraphUpdatePayload()

        updates = []
        for upd in data.get("updates", []):
            try:
                updates.append(
                    StandardUpdate(
                        standard=upd["standard"],
                        status=upd.get("status"),
                        confidence=upd.get("confidence"),
                        note=upd.get("note"),
                        misconception=upd.get("misconception"),
                    )
                )
            except (KeyError, TypeError) as e:
                logger.warning("Skipping malformed update entry: %s — %s", upd, e)

        confusions = []
        for conf in data.get("confusions", []):
            try:
                confusions.append(
                    ConfusionUpdate(
                        from_standard=conf["from_standard"],
                        to_standard=conf["to_standard"],
                        description=conf["description"],
                    )
                )
            except (KeyError, TypeError) as e:
                logger.warning("Skipping malformed confusion entry: %s — %s", conf, e)

        inferred = data.get("inferred_standards", [])
        if not isinstance(inferred, list):
            inferred = []

        payload = GraphUpdatePayload(
            updates=updates,
            confusions=confusions,
            inferred_standards=[s for s in inferred if isinstance(s, str)],
        )

        logger.info(
            "Parsed payload: %d updates, %d confusions, %d inferred standards",
            len(updates), len(confusions), len(inferred),
        )
        return payload
