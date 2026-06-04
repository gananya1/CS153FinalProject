# KnowledgeMap Tutor

**An AI math tutor for K-12 students with a living Student Knowledge Graph scaffolded by the [Common Core Coherence Map](https://tools.achievethecore.org/coherence-map/).**


---

## Problem & Motivation

Most AI tutoring systems have flat memory: a text summary of past sessions, or a vector embedding. They can recall that a student struggled, but not where in the prerequisite chain the breakdown happened, or what specific misconception is causing it.

For example, a student who says "I can't do fractions" could feel that way for any of many reasons. They may be missing third-grade multiplication fluency, or could have a misconception on fraction usage/conceptualizations (for instance, thinking that a bigger denominator means a bigger fraction). Re-explaining equivalent fractions will not help fix that underlying issue.

**KnowledgeMap Tutor** addresses this by giving every student a personal **Student Knowledge Graph (SKG)** — a live graph of CCSS math standards, updated after every exchange, that the tutor reads before every response. The graph scaffold comes from the [Achieve the Core Coherence Map](https://tools.achievethecore.org/coherence-map/), which encodes the actual prerequisite relationships between every K-12 math standard.

---

## Repo Architecture

```
mathtutor/
├── server.py                  ← FastAPI backend (REST API)
├── frontend/                  ← React + D3 frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── index.css
        └── components/
            ├── KnowledgeGraph.jsx
            └── RightPanel.jsx
├── agents/
│   ├── graph_update_agent.py  ← Conversation → structured graph mutations
│   ├── tutoring_agent.py      ← Graph context → personalized response
│   └── prompts.py             ← All LLM system prompts
├── graph/
│   ├── student_graph.py       ← NetworkX + SQLite per-student graph
│   └── schema.py              ← Node/edge types and data models
├── data/
│   └── coherence_map.py       ← Fetches CCSS graph from Achieve the Core
├── api/
│   └── session.py             ← TutoringSession: pipeline orchestration
└── scripts/
    ├── bootstrap_graph.py     ← Initialize CCSS data + demo student
```

### How It Works

**1. Student Knowledge Graph**
Each student has a SQLite-backed graph where nodes are CCSS standards (`3.NF.A.1`, `4.OA.A.3`, etc.) and edges are typed:
- `PREREQUISITE_OF` — from the Coherence Map: A → B means A must be learned before B
- `MASTERED`, `PARTIAL`, `STRUGGLES_WITH`, `MISCONCEPTION` — written by the Graph Update Agent
- `CONFUSES_WITH` — cross-standard confusion links

**2. Graph Update Agent** (runs after every exchange, uses Claude Haiku)
Analyzes the conversation and emits structured JSON:
```json
{
  "updates": [{"standard": "3.NF.A.2", "status": "MISCONCEPTION",
    "confidence": 0.1, "misconception": "Thinks larger denominator = larger fraction"}],
  "confusions": [],
  "inferred_standards": ["3.NF.A.1", "3.NF.A.2"]
}
```
These are immediately written to the student's graph.

**3. Tutoring Agent** (runs on every student message, uses Claude Sonnet)
Before generating any response, queries the student's graph for:
- Current status on the relevant standard
- Unmastered prerequisites (up to 2 hops back)
- Active misconceptions on this standard
- Cross-standard confusion links

Uses this context to decide next prompt to student: probe Socratically vs. explain directly vs. surface a prerequisite gap vs. correct a misconception.

**4. Standard Identifier** (lightweight, runs first)
Maps the student's free-text message to a CCSS standard ID so the right graph node is queried.

---

## Quickstart

### Prerequisites
- Python 3.11+
- Node.js 18+
- Anthropic API key

### 1. Install backend dependencies
```bash
cd mathtutor
pip install -r requirements.txt
pip install fastapi uvicorn python-dotenv
```

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 3. Initialize CCSS graph data
```bash
python scripts/bootstrap_graph.py
# Add --demo to also create a pre-seeded demo student
python scripts/bootstrap_graph.py --demo
```

### 4. Start the backend
```bash
uvicorn server:app --reload --port 8000
```

### 5. Install and start the frontend
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

### 6. Use the app
- Enter a Student ID (e.g. `student_001`) and grade in the sidebar
- Click **Start Session**
- Type math questions in the chat
- Switch to the **Knowledge Graph** tab to see the student's graph evolve in real time
- Click any node to inspect its status, confidence, and agent observations

---

## Evaluation

### What was tested and how

This project was evaluated through three methods:

**1. Automated unit tests**
```bash
# Unit tests only (no API key needed)
pytest tests/ -v -k "not live"

# All tests including live API calls
export ANTHROPIC_API_KEY=sk-ant-...
pytest tests/ -v
```

These validate: coherence map loading and edge structure, graph state mutations (mastered, partial, misconception, confusion links), attempt counting, JSON parsing of agent output (including malformed inputs), and the context assembly pipeline.

**2. Scripted persona testing**
The system was evaluated by running sessions using three controlled student archetypes:

| Persona | Misconception | Expected behavior |
|---------|--------------|-------------------|
| "Denominator confusion" | Thinks 1/8 > 1/4 because 8>4 | Tutor surfaces 3.NF.A.2 misconception; graph tags MISCONCEPTION with description |
| "Prerequisite gap" | Attempts 5.NF.A.1 (unlike denominators) but lacks 4.NF.A.1 (equivalent fractions) | Tutor traces back to prerequisite gap and teaches equivalent fractions first |
| "Partially correct" | Can identify unit fractions but not non-unit fractions | Graph tags 3.NF.A.1 as PARTIAL; tutor probes the specific gap |

Observations: 

**3. Live API integration tests** (requires `ANTHROPIC_API_KEY`)
```bash
pytest tests/test_agents.py -v -k "live"
```
Tests single-turn chat, graph updates post-session, standard identification, and multi-turn conversation coherence.

### Known limitations

- **Graph update reliability depends on explicitness**: The agent catches misconceptions that are verbalized ("I think bigger denominator means bigger") but is less accurate for misconceptions inferred only from a wrong numerical answer.
- **Standard identification struggles with vague messages**: "I don't get it" or "help with homework" returns no standard. The system can continue to a minimal-context response, but the standard graph doesn't update.
- **Fallback dataset covers grades 2–6**: The bundled offline dataset covers fractions, operations, and early algebra. The live Achieve the Core endpoint covers all K-12.
- **No real student validation yet**: All evaluation was conducted via scripted personas. Real student longitudinal testing in the correct age range is the most important next step.
- **Session state is in-memory**: Restarting the server clears active sessions (graph state persists in SQLite, but conversation history is lost).

---

## Potential Use Cases & Impact

**1. Individual tutoring supplement** — A student working through online pratcice resources can use this alongside them to get explanations tailored to their specific misconceptions rather than generic grade-level content.

**2. Teacher diagnostic tool** — A teacher running sessions with students can refer to the knowledge graphs created to give them an understanding of where each student's prerequisite chain breaks down. This can inform further instruction and lesson plans.

**3. Learning research** — The structured graph mutations over time are a potential data source for studying how mathematical misconceptions evolve and resolve — which can be hard to capture in existing assessments.

---

## Future Steps

- **Real student study** — Have real students run multiple sessions and measure performance on targeted standards
- **A/B evaluation** — Run sessions with students split so that half are using the knowledge graph backend and half use flat memory.
- **Spaced repetition** — Have the tutor resurface standards the graph predicts are decaying based on last-seen timestamps
- **Full K-12 standard coverage** — As mentioned in limitations, the current offline fallback covers grades 2-6. Full coverage requires the live ATC endpoint
- **Affective state detection** — More nuanced emotional engagement, like detecting frustration or disengagement signals and adjusting tutoring strategy would be interesting. This would require careful thought and implementation though

## Disclosures

Claude was used to aid in code generation and to find gaps in testing approaches.

**External data sources:**
- [Achieve the Core Coherence Map](https://tools.achievethecore.org/coherence-map/) — CCSS standards and prerequisite relationships. The open-source repo is at [github.com/achievethecore/atc-coherence-map](https://github.com/achievethecore/atc-coherence-map). No code from that repo was used; only the public data API endpoint is accessed.
- Common Core State Standards for Mathematics (public domain)

No existing tutoring system codebases were forked or copied.