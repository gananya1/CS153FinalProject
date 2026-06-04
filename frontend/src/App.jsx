import { useState, useRef, useEffect, useCallback } from 'react'
import KnowledgeGraph from './components/KnowledgeGraph'
import RightPanel from './components/RightPanel'

const API = ''  // proxied via vite to localhost:8000

async function apiPost(path, body) {
  const r = await fetch(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`API error: ${r.status}`)
  return r.json()
}

async function apiGet(path) {
  const r = await fetch(API + path)
  if (!r.ok) throw new Error(`API error: ${r.status}`)
  return r.json()
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  )
}

export default function App() {
  const [activeTab, setActiveTab] = useState('chat')    // 'chat' | 'graph'
  const [studentId, setStudentId] = useState('')
  const [studentName, setStudentName] = useState('')
  const [grade, setGrade] = useState('4')
  const [sessionActive, setSessionActive] = useState(false)

  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  const [graphData, setGraphData] = useState(null)
  const [graphSummary, setGraphSummary] = useState({})
  const [selectedNode, setSelectedNode] = useState(null)

  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const startSession = async () => {
    if (!studentId.trim()) return
    try {
      await apiPost('/api/session/start', {
        student_id: studentId,
        grade: parseInt(grade),
        name: studentName || studentId,
      })
      setSessionActive(true)
      setMessages([])
      // Load existing graph data if any
      await refreshGraph()
    } catch (e) {
      console.error(e)
    }
  }

  const refreshGraph = useCallback(async () => {
    if (!studentId) return
    try {
      const data = await apiGet(`/api/graph/${studentId}?grade=${grade}`)
      setGraphData(data)
      setGraphSummary(data.summary || {})
    } catch (e) {
      // Graph may not exist yet on first load — that's fine
    }
  }, [studentId, grade])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading || !sessionActive) return
    setInput('')

    setMessages(prev => [...prev, { role: 'user', content: text }])
    setLoading(true)

    try {
      const data = await apiPost('/api/chat', {
        student_id: studentId,
        message: text,
        grade: parseInt(grade),
        name: studentName || studentId,
      })
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.response,
        standard: data.focus_standard,
      }])
      if (data.graph_summary) setGraphSummary(data.graph_summary)
      // Refresh graph data after each exchange
      await refreshGraph()
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: "Sorry, I couldn't connect to the tutor server. Make sure the backend is running (`uvicorn server:app --reload`).",
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="app-shell">
      {/* Top bar */}
      <header className="topbar">
        <div className="topbar-logo">
          KnowledgeMap Tutor
          <span>K-12 Math · CCSS Scaffolded</span>
        </div>
        <div className="topbar-tabs">
          <button className={`tab-btn ${activeTab === 'chat' ? 'active' : ''}`} onClick={() => setActiveTab('chat')}>
            Chat
          </button>
          <button className={`tab-btn ${activeTab === 'graph' ? 'active' : ''}`} onClick={() => { setActiveTab('graph'); refreshGraph() }}>
            Knowledge Graph
          </button>
        </div>
      </header>

      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-section-label">Student</div>

        <div className="grade-input-wrap">
          <label>Student ID</label>
          <input
            placeholder="e.g. student_001"
            value={studentId}
            onChange={e => setStudentId(e.target.value)}
            disabled={sessionActive}
          />
        </div>
        <div className="grade-input-wrap">
          <label>Name (optional)</label>
          <input
            placeholder="e.g. Alex"
            value={studentName}
            onChange={e => setStudentName(e.target.value)}
            disabled={sessionActive}
          />
        </div>
        <div className="grade-input-wrap">
          <label>Grade</label>
          <select value={grade} onChange={e => setGrade(e.target.value)} disabled={sessionActive}>
            {['K','1','2','3','4','5','6','7','8'].map(g => (
              <option key={g} value={g}>Grade {g}</option>
            ))}
          </select>
        </div>
        <div className="grade-input-wrap">
          <button
            className="start-btn"
            onClick={sessionActive ? () => { setSessionActive(false); setMessages([]); setGraphData(null) } : startSession}
            disabled={!studentId.trim()}
          >
            {sessionActive ? 'End Session' : 'Start Session'}
          </button>
        </div>

        {sessionActive && (
          <>
            <div className="sidebar-section-label" style={{ marginTop: 8 }}>Session</div>
            <div className="sidebar-item active">
              <div className="sidebar-item-name">{studentName || studentId}</div>
              <div className="sidebar-item-sub">Grade {grade} · {messages.filter(m => m.role === 'user').length} exchanges</div>
            </div>
            {graphSummary?.by_status?.MASTERED > 0 && (
              <div className="sidebar-item">
                <div className="sidebar-item-name" style={{ color: 'var(--green)', fontSize: 12 }}>
                  ✓ {graphSummary.by_status.MASTERED} mastered
                </div>
              </div>
            )}
            {(graphSummary?.by_status?.MISCONCEPTION > 0) && (
              <div className="sidebar-item">
                <div className="sidebar-item-name" style={{ color: 'var(--red)', fontSize: 12 }}>
                  ⚠ {graphSummary.by_status.MISCONCEPTION} misconception{graphSummary.by_status.MISCONCEPTION > 1 ? 's' : ''}
                </div>
              </div>
            )}
          </>
        )}

        <div style={{ flex: 1 }} />
        <div style={{ padding: '8px', fontSize: 10, color: 'var(--text-dim)', lineHeight: 1.6 }}>
          Graph scaffolded by the{' '}
          <a href="https://tools.achievethecore.org/coherence-map/" target="_blank" rel="noreferrer"
            style={{ color: 'var(--amber)', textDecoration: 'none' }}>
            CCSS Coherence Map
          </a>
        </div>
      </aside>

      {/* Main area */}
      <main className="main-area">
        {activeTab === 'chat' ? (
          <div className="chat-view">
            {!sessionActive ? (
              <div className="welcome">
                <div className="welcome-icon">◎</div>
                <h2>KnowledgeMap Tutor</h2>
                <p>Enter a student ID and grade, then start a session. The tutor builds a live knowledge graph of the student's understanding as you chat.</p>
              </div>
            ) : (
              <>
                <div className="chat-messages">
                  {messages.length === 0 && (
                    <div className="welcome" style={{ height: 'auto', padding: '40px 0' }}>
                      <div className="welcome-icon" style={{ fontSize: 28 }}>✦</div>
                      <p>Session started for <strong style={{ color: 'var(--text)' }}>{studentName || studentId}</strong> (Grade {grade}).<br />Ask a math question to begin.</p>
                    </div>
                  )}
                  {messages.map((msg, i) => (
                    <div key={i} className={`msg ${msg.role}`}>
                      <div className="msg-avatar">
                        {msg.role === 'user' ? '👤' : '◎'}
                      </div>
                      <div className="msg-bubble">
                        {msg.content}
                        {msg.standard && (
                          <div>
                            <span className="msg-standard-tag">{msg.standard}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  {loading && (
                    <div className="msg assistant">
                      <div className="msg-avatar">◎</div>
                      <div className="typing-indicator">
                        <div className="typing-dot" />
                        <div className="typing-dot" />
                        <div className="typing-dot" />
                      </div>
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </div>

                <div className="chat-input-area">
                  <textarea
                    ref={textareaRef}
                    className="chat-input"
                    placeholder="Ask a math question…"
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    rows={1}
                    disabled={loading}
                  />
                  <button className="send-btn" onClick={sendMessage} disabled={!input.trim() || loading}>
                    <SendIcon />
                  </button>
                </div>
              </>
            )}
          </div>
        ) : (
          <div className="graph-view">
            <div className="graph-toolbar">
              <span className="graph-toolbar-title">
                {studentId ? `${studentName || studentId}'s Knowledge Graph` : 'Knowledge Graph'}
              </span>
              <div className="legend">
                {[
                  { color: 'var(--green)', label: 'Mastered' },
                  { color: 'var(--yellow)', label: 'Partial' },
                  { color: 'var(--red)', label: 'Struggling / Misconception' },
                  { color: 'var(--border)', label: 'Unseen context' },
                ].map(({ color, label }) => (
                  <div key={label} className="legend-item">
                    <div className="legend-dot" style={{ background: color }} />
                    <span>{label}</span>
                  </div>
                ))}
              </div>
            </div>
            <KnowledgeGraph
              graphData={graphData}
              onNodeClick={setSelectedNode}
              selectedNode={selectedNode}
            />
          </div>
        )}
      </main>

      {/* Right panel */}
      <RightPanel
        graphSummary={graphSummary}
        selectedNode={selectedNode}
        studentId={sessionActive ? studentId : null}
      />
    </div>
  )
}
