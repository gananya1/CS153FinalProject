"""
FastAPI backend for KnowledgeMap Tutor.
Exposes REST endpoints consumed by the React frontend.

Start with:
    uvicorn server:app --reload --port 8000
"""
from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.session import TutoringSession
from graph.student_graph import StudentGraph
from data.coherence_map import load_coherence_graph, get_prerequisites

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="KnowledgeMap Tutor API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store (keyed by student_id)
# In production this would be Redis or similar
_sessions: dict[str, TutoringSession] = {}

DB_DIR = Path(__file__).parent / "data" / "students"


def get_or_create_session(student_id: str, grade: int, name: Optional[str] = None) -> TutoringSession:
    if student_id not in _sessions:
        _sessions[student_id] = TutoringSession(
            student_id=student_id,
            grade=grade,
            student_name=name or student_id,
            db_dir=DB_DIR,
        )
    return _sessions[student_id]


# Request / Response models

class StartSessionRequest(BaseModel):
    student_id: str
    grade: int
    name: Optional[str] = None

class ChatRequest(BaseModel):
    student_id: str
    message: str
    grade: int = 4
    name: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    focus_standard: Optional[str]
    graph_summary: dict

class GraphStateResponse(BaseModel):
    student_id: str
    nodes: list[dict]
    edges: list[dict]
    summary: dict

class StandardDetailResponse(BaseModel):
    standard_id: str
    description: str
    grade: str
    domain: str
    prerequisites: list[dict]
    dependents: list[str]
    student_state: Optional[dict]
    misconceptions: list[dict]


# Endpoints

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/session/start")
def start_session(req: StartSessionRequest):
    get_or_create_session(req.student_id, req.grade, req.name)
    return {"status": "ready", "student_id": req.student_id}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session = get_or_create_session(req.student_id, req.grade, req.name)

    # Identify standard before chat (for response metadata)
    focus_standard = session.identifier.identify(req.message, grade=req.grade)

    response_text = session.chat(req.message)
    summary = session.student_graph.summary()

    return ChatResponse(
        response=response_text,
        focus_standard=focus_standard,
        graph_summary=summary,
    )


@app.get("/api/graph/{student_id}", response_model=GraphStateResponse)
def get_graph(student_id: str, grade: int = 4):
    sg = StudentGraph(student_id=student_id, grade=grade, db_dir=DB_DIR)
    cg = sg._cg

    states = {s.standard_id: s for s in sg.all_states()}

    nodes = []
    seen_ids = set(states.keys())

    # Include all seen standards + their immediate neighbors for context
    expanded = set(seen_ids)
    for sid in seen_ids:
        if sid in cg:
            for neighbor in cg.neighbors(sid):
                expanded.add(neighbor)
            for pred in cg.predecessors(sid):
                expanded.add(pred)

    for sid in expanded:
        node_data = cg.nodes.get(sid, {})
        state = states.get(sid)
        nodes.append({
            "id": sid,
            "grade": node_data.get("grade", ""),
            "domain": node_data.get("domain", ""),
            "description": node_data.get("description", ""),
            "status": state.status if state else "UNSEEN",
            "confidence": state.confidence if state else 0.0,
            "attempts": state.attempts if state else 0,
            "notes": state.notes if state else [],
        })

    edges = []
    for u, v, data in cg.edges(data=True):
        if u in expanded and v in expanded:
            edges.append({
                "source": u,
                "target": v,
                "type": data.get("type", ""),
            })

    # Also add student-specific edges
    rows = sg._conn.execute("SELECT * FROM student_edges").fetchall()
    for row in rows:
        edges.append({
            "source": row["from_node"],
            "target": row["to_node"],
            "type": row["edge_type"],
            "description": row["description"],
        })

    summary = sg.summary()
    sg.close()
    return GraphStateResponse(
        student_id=student_id,
        nodes=nodes,
        edges=edges,
        summary=summary,
    )


@app.get("/api/standard/{standard_id}")
def get_standard_detail(standard_id: str, student_id: Optional[str] = None, grade: int = 4):
    cg = load_coherence_graph()
    node_data = cg.nodes.get(standard_id)
    if not node_data:
        raise HTTPException(status_code=404, detail=f"Standard {standard_id} not found")

    prereq_ids = get_prerequisites(standard_id, graph=cg, depth=1)
    dependent_ids = [
        v for u, v, d in cg.edges(standard_id, data=True)
        if d.get("type") == "PREREQUISITE_OF"
    ]

    student_state = None
    misconceptions = []
    if student_id:
        sg = StudentGraph(student_id=student_id, grade=grade, db_dir=DB_DIR)
        state = sg.get_state(standard_id)
        if state:
            student_state = {
                "status": state.status,
                "confidence": state.confidence,
                "attempts": state.attempts,
                "notes": state.notes,
            }
        ctx = sg.get_context_for_tutor(standard_id)
        misconceptions = ctx.get("misconceptions", [])
        sg.close()

    prereqs = []
    for pid in prereq_ids:
        pdata = cg.nodes.get(pid, {})
        prereqs.append({
            "standard_id": pid,
            "description": pdata.get("description", ""),
            "grade": pdata.get("grade", ""),
        })

    return {
        "standard_id": standard_id,
        "description": node_data.get("description", ""),
        "grade": node_data.get("grade", ""),
        "domain": node_data.get("domain", ""),
        "prerequisites": prereqs,
        "dependents": dependent_ids,
        "student_state": student_state,
        "misconceptions": misconceptions,
    }


@app.get("/api/students")
def list_students():
    """List all students who have session data."""
    db_dir = DB_DIR
    if not db_dir.exists():
        return {"students": []}
    students = []
    for db_file in db_dir.glob("*.db"):
        student_id = db_file.stem
        students.append({"student_id": student_id})
    return {"students": students}


# Serve React frontend in production
frontend_build = Path(__file__).parent / "frontend" / "dist"
if frontend_build.exists():
    app.mount("/assets", StaticFiles(directory=frontend_build / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        return FileResponse(frontend_build / "index.html")
