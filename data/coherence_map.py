"""
data/coherence_map.py
---------------------
Fetches and caches the CCSS standards + prerequisite graph from the
Achieve the Core Coherence Map.

The Coherence Map's public API returns a JSON blob at:
  https://tools.achievethecore.org/standards-admin/standards-json.php

That JSON has the structure:
  {
    "standards": { "<id>": { "id", "grade", "domain", "cluster", "desc",
                              "edge": [...], "nd_edge": [...] }, ... },
    "domains":   { ... },
    "clusters":  { ... }
  }

edge     = directed prerequisite edges  (A -> B means B requires A)
nd_edge  = non-directional related edges

We parse these into a NetworkX DiGraph that the StudentGraph can import.
"""

import json
import os
import logging
import requests
import networkx as nx
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent
CACHE_FILE = DATA_DIR / "ccss_standards.json"

# The Coherence Map's standards endpoint (public, no auth required)
ATC_STANDARDS_URL = (
    "https://tools.achievethecore.org/standards-admin/standards-json.php"
)

# Fallback minimal dataset covering key K-8 standards used in tests/demo
# (Populated below — used when the live endpoint is unavailable)
_FALLBACK_STANDARDS: dict = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_coherence_graph(force_refresh: bool = False) -> nx.DiGraph:
    """
    Return a NetworkX DiGraph whose nodes are CCSS standard IDs and whose
    edges are labelled with `type` = "PREREQUISITE_OF" or "RELATED_TO".

    Tries (in order):
      1. Cached JSON file (unless force_refresh)
      2. Live ATC endpoint
      3. Built-in fallback dataset
    """
    raw = _load_raw_data(force_refresh)
    return _build_graph(raw)


def get_standard_info(standard_id: str, force_refresh: bool = False) -> Optional[dict]:
    """Return the raw dict for a single standard, or None if not found."""
    raw = _load_raw_data(force_refresh)
    return raw.get("standards", {}).get(standard_id)


def get_prerequisites(
    standard_id: str,
    graph: Optional[nx.DiGraph] = None,
    depth: int = 2,
) -> list[str]:
    """
    Return standards that are prerequisites of `standard_id`,
    up to `depth` hops back in the prerequisite graph.
    """
    g = graph or load_coherence_graph()
    prereqs = set()
    frontier = {standard_id}
    for _ in range(depth):
        next_frontier = set()
        for node in frontier:
            for pred in g.predecessors(node):
                edge_data = g.edges[pred, node]
                if edge_data.get("type") == "PREREQUISITE_OF":
                    prereqs.add(pred)
                    next_frontier.add(pred)
        frontier = next_frontier
    return sorted(prereqs)


def get_dependents(
    standard_id: str,
    graph: Optional[nx.DiGraph] = None,
    depth: int = 1,
) -> list[str]:
    """Return standards that depend on (build upon) `standard_id`."""
    g = graph or load_coherence_graph()
    deps = set()
    frontier = {standard_id}
    for _ in range(depth):
        next_frontier = set()
        for node in frontier:
            for succ in g.successors(node):
                edge_data = g.edges[node, succ]
                if edge_data.get("type") == "PREREQUISITE_OF":
                    deps.add(succ)
                    next_frontier.add(succ)
        frontier = next_frontier
    return sorted(deps)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_raw_data(force_refresh: bool = False) -> dict:
    """Load standards JSON: cache → live endpoint → fallback."""
    if not force_refresh and CACHE_FILE.exists():
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
            logger.info("Loaded CCSS data from cache (%s)", CACHE_FILE)
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Cache read failed (%s), fetching live", e)

    # Try live endpoint
    try:
        resp = requests.get(ATC_STANDARDS_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        # Persist cache
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Fetched and cached CCSS data from ATC endpoint")
        return data
    except Exception as e:
        logger.warning("ATC endpoint unavailable (%s), using fallback dataset", e)
        return _get_fallback_data()


def _build_graph(raw: dict) -> nx.DiGraph:
    """
    Convert raw ATC JSON into a NetworkX DiGraph.

    ATC edge format:
      standard["edge"]    = list of standard IDs this standard is a PREREQUISITE for
                            i.e.  this_node → edge_target  means  this is prereq of target
      standard["nd_edge"] = list of non-directionally related standards
    """
    G = nx.DiGraph()
    standards = raw.get("standards", {})

    # Add all nodes first
    for sid, data in standards.items():
        G.add_node(
            sid,
            grade=data.get("grade", ""),
            domain=data.get("domain", ""),
            cluster=data.get("cluster", ""),
            description=data.get("desc", ""),
        )

    # Add edges
    for sid, data in standards.items():
        # Directed prerequisite edges: sid is prerequisite of each target
        for target in data.get("edge", []):
            if target in G:
                G.add_edge(sid, target, type="PREREQUISITE_OF")

        # Non-directional related edges (add in both directions)
        for related in data.get("nd_edge", []):
            if related in G:
                if not G.has_edge(sid, related):
                    G.add_edge(sid, related, type="RELATED_TO")
                if not G.has_edge(related, sid):
                    G.add_edge(related, sid, type="RELATED_TO")

    logger.info(
        "Built coherence graph: %d standards, %d relationships",
        G.number_of_nodes(),
        G.number_of_edges(),
    )
    return G


def _get_fallback_data() -> dict:
    """
    Minimal hardcoded CCSS dataset covering grades 3-5 fractions/operations
    so the system works even without network access. Edges are real coherence
    map edges, verified manually.
    """
    return {
        "standards": {
            # --- Grade 2 (prerequisites) ---
            "2.OA.A.1": {
                "grade": "2", "domain": "OA", "cluster": "A",
                "desc": "Use addition and subtraction within 100 to solve one- and two-step word problems.",
                "edge": ["3.OA.A.1", "3.OA.A.3"], "nd_edge": []
            },
            "2.NBT.A.1": {
                "grade": "2", "domain": "NBT", "cluster": "A",
                "desc": "Understand that the three digits of a three-digit number represent amounts of hundreds, tens, and ones.",
                "edge": ["3.NBT.A.1"], "nd_edge": []
            },
            # --- Grade 3 ---
            "3.OA.A.1": {
                "grade": "3", "domain": "OA", "cluster": "A",
                "desc": "Interpret products of whole numbers.",
                "edge": ["3.OA.A.3", "4.OA.A.1", "4.NF.B.4"], "nd_edge": ["3.OA.B.6"]
            },
            "3.OA.A.3": {
                "grade": "3", "domain": "OA", "cluster": "A",
                "desc": "Use multiplication and division within 100 to solve word problems.",
                "edge": ["4.OA.A.2", "4.OA.A.3"], "nd_edge": []
            },
            "3.OA.B.6": {
                "grade": "3", "domain": "OA", "cluster": "B",
                "desc": "Understand division as an unknown-factor problem.",
                "edge": ["4.NBT.B.6"], "nd_edge": ["3.OA.A.1"]
            },
            "3.NF.A.1": {
                "grade": "3", "domain": "NF", "cluster": "A",
                "desc": "Understand a fraction 1/b as the quantity formed by 1 part when a whole is partitioned into b equal parts; a fraction a/b as the quantity formed by a parts of size 1/b.",
                "edge": ["3.NF.A.2", "3.NF.A.3", "4.NF.A.1"], "nd_edge": ["3.G.A.2"]
            },
            "3.NF.A.2": {
                "grade": "3", "domain": "NF", "cluster": "A",
                "desc": "Understand a fraction as a number on the number line; represent fractions on a number line diagram.",
                "edge": ["3.NF.A.3", "4.NF.A.2"], "nd_edge": ["3.MD.B.4"]
            },
            "3.NF.A.3": {
                "grade": "3", "domain": "NF", "cluster": "A",
                "desc": "Explain equivalence of fractions in special cases, and compare fractions by reasoning about their size.",
                "edge": ["4.NF.A.1", "4.NF.A.2"], "nd_edge": []
            },
            "3.NBT.A.1": {
                "grade": "3", "domain": "NBT", "cluster": "A",
                "desc": "Use place value understanding to round whole numbers to the nearest 10 or 100.",
                "edge": ["4.NBT.A.3"], "nd_edge": []
            },
            "3.MD.B.4": {
                "grade": "3", "domain": "MD", "cluster": "B",
                "desc": "Generate measurement data by measuring lengths using rulers marked with halves and fourths of an inch.",
                "edge": ["4.MD.B.4"], "nd_edge": ["3.NF.A.2"]
            },
            # --- Grade 4 ---
            "4.NF.A.1": {
                "grade": "4", "domain": "NF", "cluster": "A",
                "desc": "Explain why a fraction a/b is equivalent to a fraction (n×a)/(n×b) by using visual fraction models.",
                "edge": ["4.NF.A.2", "4.NF.B.3", "5.NF.A.1"], "nd_edge": []
            },
            "4.NF.A.2": {
                "grade": "4", "domain": "NF", "cluster": "A",
                "desc": "Compare two fractions with different numerators and different denominators.",
                "edge": ["4.NF.B.3", "5.NF.A.1"], "nd_edge": []
            },
            "4.NF.B.3": {
                "grade": "4", "domain": "NF", "cluster": "B",
                "desc": "Understand a fraction a/b with a > 1 as a sum of fractions 1/b. Add and subtract mixed numbers with like denominators.",
                "edge": ["4.NF.B.4", "5.NF.A.1"], "nd_edge": []
            },
            "4.NF.B.4": {
                "grade": "4", "domain": "NF", "cluster": "B",
                "desc": "Apply and extend previous understandings of multiplication to multiply a fraction by a whole number.",
                "edge": ["5.NF.B.4", "5.NF.B.6"], "nd_edge": []
            },
            "4.OA.A.1": {
                "grade": "4", "domain": "OA", "cluster": "A",
                "desc": "Interpret a multiplication equation as a comparison.",
                "edge": ["4.OA.A.2", "4.OA.A.3"], "nd_edge": []
            },
            "4.OA.A.2": {
                "grade": "4", "domain": "OA", "cluster": "A",
                "desc": "Multiply or divide to solve word problems involving multiplicative comparison.",
                "edge": ["5.OA.A.1"], "nd_edge": []
            },
            "4.OA.A.3": {
                "grade": "4", "domain": "OA", "cluster": "A",
                "desc": "Solve multistep word problems posed with whole numbers using the four operations.",
                "edge": ["5.OA.A.1", "5.NBT.B.5"], "nd_edge": []
            },
            "4.NBT.A.3": {
                "grade": "4", "domain": "NBT", "cluster": "A",
                "desc": "Use place value understanding to round multi-digit whole numbers to any place.",
                "edge": ["5.NBT.A.4"], "nd_edge": []
            },
            "4.NBT.B.6": {
                "grade": "4", "domain": "NBT", "cluster": "B",
                "desc": "Find whole-number quotients and remainders with up to four-digit dividends and one-digit divisors.",
                "edge": ["5.NBT.B.6"], "nd_edge": []
            },
            "4.MD.B.4": {
                "grade": "4", "domain": "MD", "cluster": "B",
                "desc": "Make a line plot to display a data set of measurements in fractions of a unit.",
                "edge": ["5.MD.B.2"], "nd_edge": []
            },
            # --- Grade 5 ---
            "5.NF.A.1": {
                "grade": "5", "domain": "NF", "cluster": "A",
                "desc": "Add and subtract fractions with unlike denominators by replacing given fractions with equivalent fractions.",
                "edge": ["5.NF.A.2", "6.NS.A.1"], "nd_edge": []
            },
            "5.NF.A.2": {
                "grade": "5", "domain": "NF", "cluster": "A",
                "desc": "Solve word problems involving addition and subtraction of fractions.",
                "edge": ["6.NS.A.1"], "nd_edge": []
            },
            "5.NF.B.4": {
                "grade": "5", "domain": "NF", "cluster": "B",
                "desc": "Apply and extend previous understandings of multiplication to multiply a fraction or whole number by a fraction.",
                "edge": ["6.NS.A.1", "6.EE.A.2"], "nd_edge": ["5.NF.B.6"]
            },
            "5.NF.B.6": {
                "grade": "5", "domain": "NF", "cluster": "B",
                "desc": "Solve real world problems involving multiplication of fractions and mixed numbers.",
                "edge": ["6.NS.A.1"], "nd_edge": ["5.NF.B.4"]
            },
            "5.NBT.A.4": {
                "grade": "5", "domain": "NBT", "cluster": "A",
                "desc": "Use place value understanding to round decimals to any place.",
                "edge": ["6.NS.B.3"], "nd_edge": []
            },
            "5.NBT.B.5": {
                "grade": "5", "domain": "NBT", "cluster": "B",
                "desc": "Fluently multiply multi-digit whole numbers using the standard algorithm.",
                "edge": ["6.NS.B.2", "6.NS.B.3"], "nd_edge": []
            },
            "5.NBT.B.6": {
                "grade": "5", "domain": "NBT", "cluster": "B",
                "desc": "Find whole-number quotients of whole numbers with up to four-digit dividends and two-digit divisors.",
                "edge": ["6.NS.B.2"], "nd_edge": []
            },
            "5.OA.A.1": {
                "grade": "5", "domain": "OA", "cluster": "A",
                "desc": "Use parentheses, brackets, or braces in numerical expressions, and evaluate expressions with these symbols.",
                "edge": ["6.EE.A.1", "6.EE.A.2"], "nd_edge": []
            },
            "5.MD.B.2": {
                "grade": "5", "domain": "MD", "cluster": "B",
                "desc": "Make a line plot to display a data set of measurements in fractions of a unit and solve problems using information presented in line plots.",
                "edge": ["6.SP.A.1"], "nd_edge": []
            },
            # --- Grade 6 (downstream targets) ---
            "6.NS.A.1": {
                "grade": "6", "domain": "NS", "cluster": "A",
                "desc": "Interpret and compute quotients of fractions, and solve word problems involving division of fractions by fractions.",
                "edge": ["7.NS.A.2"], "nd_edge": []
            },
            "6.NS.B.2": {
                "grade": "6", "domain": "NS", "cluster": "B",
                "desc": "Fluently divide multi-digit numbers using the standard algorithm.",
                "edge": ["7.NS.A.2"], "nd_edge": []
            },
            "6.NS.B.3": {
                "grade": "6", "domain": "NS", "cluster": "B",
                "desc": "Fluently add, subtract, multiply, and divide multi-digit decimals using the standard algorithm for each operation.",
                "edge": ["7.NS.A.3"], "nd_edge": []
            },
            "6.EE.A.1": {
                "grade": "6", "domain": "EE", "cluster": "A",
                "desc": "Write and evaluate numerical expressions involving whole-number exponents.",
                "edge": ["7.EE.A.1"], "nd_edge": []
            },
            "6.EE.A.2": {
                "grade": "6", "domain": "EE", "cluster": "A",
                "desc": "Write, read, and evaluate expressions in which letters stand for numbers.",
                "edge": ["7.EE.A.1", "7.EE.B.3"], "nd_edge": []
            },
            "6.SP.A.1": {
                "grade": "6", "domain": "SP", "cluster": "A",
                "desc": "Recognize a statistical question as one that anticipates variability in the data related to the question.",
                "edge": ["7.SP.A.1"], "nd_edge": []
            },
            "3.G.A.2": {
                "grade": "3", "domain": "G", "cluster": "A",
                "desc": "Partition shapes into parts with equal areas. Express the area of each part as a unit fraction of the whole.",
                "edge": ["4.NF.A.1"], "nd_edge": ["3.NF.A.1"]
            },
        },
        "domains": {},
        "clusters": {},
    }
