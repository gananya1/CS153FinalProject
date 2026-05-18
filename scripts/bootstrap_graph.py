#!/usr/bin/env python3
"""
scripts/bootstrap_graph.py
---------------------------
Initialize the system:
  1. Fetch and cache the CCSS coherence map from Achieve the Core
  2. Print a summary of what was loaded
  3. Optionally seed a demo student graph

Run from the project root:
    python scripts/bootstrap_graph.py
    python scripts/bootstrap_graph.py --refresh   # force re-fetch from ATC
    python scripts/bootstrap_graph.py --demo      # also create a demo student
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.coherence_map import load_coherence_graph, CACHE_FILE
from graph.student_graph import StudentGraph
from graph.schema import GraphUpdatePayload, StandardUpdate, EdgeType

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Bootstrap the KnowledgeMap Tutor data")
    parser.add_argument("--refresh", action="store_true", help="Force re-fetch from ATC endpoint")
    parser.add_argument("--demo", action="store_true", help="Create a demo student graph")
    args = parser.parse_args()

    print("=" * 60)
    print("KnowledgeMap Tutor — Graph Bootstrap")
    print("=" * 60)

    # 1. Load coherence graph
    print(f"\n{'Re-fetching' if args.refresh else 'Loading'} CCSS coherence map...")
    G = load_coherence_graph(force_refresh=args.refresh)

    print(f"\n✓ Loaded coherence graph:")
    print(f"  Standards (nodes): {G.number_of_nodes()}")
    print(f"  Relationships (edges): {G.number_of_edges()}")

    # Count by grade
    grade_counts: dict[str, int] = {}
    for node, data in G.nodes(data=True):
        g = data.get("grade", "?")
        grade_counts[g] = grade_counts.get(g, 0) + 1

    print(f"\n  Standards by grade:")
    for grade in sorted(grade_counts.keys(), key=lambda x: (x.isdigit(), x)):
        print(f"    Grade {grade:>2}: {grade_counts[grade]} standards")

    # Count edge types
    prereq_count = sum(
        1 for _, _, d in G.edges(data=True) if d.get("type") == "PREREQUISITE_OF"
    )
    related_count = sum(
        1 for _, _, d in G.edges(data=True) if d.get("type") == "RELATED_TO"
    )
    print(f"\n  Edge types:")
    print(f"    PREREQUISITE_OF: {prereq_count}")
    print(f"    RELATED_TO:      {related_count}")

    if CACHE_FILE.exists():
        size_kb = CACHE_FILE.stat().st_size / 1024
        print(f"\n  Cache file: {CACHE_FILE} ({size_kb:.1f} KB)")

    # 2. Demo student
    if args.demo:
        print("\n" + "=" * 60)
        print("Creating demo student graph...")
        _create_demo_student(G)

    print("\n✓ Bootstrap complete. Ready to start tutoring sessions.\n")


def _create_demo_student(G):
    """
    Create a demo student (grade 4) who:
    - Has mastered grade 3 multiplication basics
    - Is partially understanding unit fractions (3.NF.A.1)
    - Has a misconception about fraction size (larger denominator = larger fraction)
    - Has not yet encountered equivalent fractions (4.NF.A.1)
    """
    student_id = "demo_student"
    sg = StudentGraph(student_id=student_id, grade=4)

    payload = GraphUpdatePayload(
        updates=[
            StandardUpdate(
                standard="3.OA.A.1",
                status=EdgeType.MASTERED,
                confidence=0.9,
                note="Solid understanding of multiplication as repeated addition",
            ),
            StandardUpdate(
                standard="3.OA.A.3",
                status=EdgeType.MASTERED,
                confidence=0.85,
                note="Can solve multiplication word problems reliably",
            ),
            StandardUpdate(
                standard="3.NF.A.1",
                status=EdgeType.PARTIAL,
                confidence=0.45,
                note="Understands unit fractions but struggles with non-unit fractions (a/b where a>1)",
            ),
            StandardUpdate(
                standard="3.NF.A.2",
                status=EdgeType.MISCONCEPTION,
                confidence=0.1,
                note="Consistently places fractions wrong on number line",
                misconception="Thinks larger denominator means the fraction is placed further right on the number line (confuses denominator size with magnitude)",
            ),
            StandardUpdate(
                standard="3.NF.A.3",
                status="STRUGGLES_WITH",
                confidence=0.2,
                note="Cannot reliably compare fractions; relies on denominator size heuristic",
            ),
        ]
    )

    sg.apply_updates(payload)
    sg.close()

    print(f"  ✓ Demo student '{student_id}' created (grade 4)")
    print(f"    Mastered: 3.OA.A.1, 3.OA.A.3")
    print(f"    Partial:  3.NF.A.1")
    print(f"    Misconception: 3.NF.A.2 (denominator size ≠ fraction magnitude)")
    print(f"    Struggles: 3.NF.A.3")
    print(f"\n  Try: python scripts/demo_chat.py --student demo_student --grade 4")


if __name__ == "__main__":
    main()
