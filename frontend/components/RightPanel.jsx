export default function RightPanel({ graphSummary, selectedNode, studentId }) {
  const byStatus = graphSummary?.by_status || {}
  const total = graphSummary?.total_standards_seen || 0
  const mastered = byStatus['MASTERED'] || 0
  const partial = byStatus['PARTIAL'] || 0
  const struggles = byStatus['STRUGGLES_WITH'] || 0
  const misconceptions = byStatus['MISCONCEPTION'] || 0

  return (
    <div className="right-panel">

      {/* Student stats */}
      {studentId && (
        <div className="panel-card">
          <div className="panel-card-title">Knowledge Graph</div>
          <div className="stat-row">
            <span className="stat-label">Standards touched</span>
            <span className="stat-value" style={{ color: 'var(--text)' }}>{total}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Mastered</span>
            <span className="stat-value" style={{ color: 'var(--green)' }}>{mastered}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Partial</span>
            <span className="stat-value" style={{ color: 'var(--yellow)' }}>{partial}</span>
          </div>
          <div className="stat-row">
            <span className="stat-label">Struggling</span>
            <span className="stat-value" style={{ color: 'var(--red)' }}>{struggles}</span>
          </div>
          {misconceptions > 0 && (
            <div className="stat-row">
              <span className="stat-label">Misconceptions</span>
              <span className="stat-value" style={{ color: 'var(--red)' }}>⚠ {misconceptions}</span>
            </div>
          )}
        </div>
      )}

      {/* Selected node detail */}
      {selectedNode ? (
        <div className="panel-card">
          <div className="panel-card-title">Standard Detail</div>
          <div className="node-detail">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span className="node-detail-id">{selectedNode.id}</span>
              <span className={`status-badge status-${selectedNode.status}`}>
                {selectedNode.status}
              </span>
            </div>

            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              Grade {selectedNode.grade} · {selectedNode.domain}
            </div>

            <div className="node-detail-desc">{selectedNode.description}</div>

            {selectedNode.status !== 'UNSEEN' && (
              <>
                <div style={{ marginTop: 4 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Confidence</span>
                    <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text)' }}>
                      {(selectedNode.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="confidence-bar">
                    <div
                      className="confidence-fill"
                      style={{
                        width: `${selectedNode.confidence * 100}%`,
                        background: selectedNode.status === 'MASTERED'
                          ? 'var(--green)'
                          : selectedNode.status === 'PARTIAL'
                          ? 'var(--yellow)'
                          : 'var(--red)'
                      }}
                    />
                  </div>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {selectedNode.attempts} attempt{selectedNode.attempts !== 1 ? 's' : ''}
                </div>
              </>
            )}

            {selectedNode.notes && selectedNode.notes.length > 0 && (
              <div className="node-notes">
                <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>
                  Agent observations
                </div>
                {selectedNode.notes.slice(-3).map((note, i) => (
                  <div key={i} className="node-note">{note}</div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="panel-card">
          <div className="panel-card-title">Standard Detail</div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', textAlign: 'center', padding: '16px 0' }}>
            Click any node in the graph to inspect it
          </div>
        </div>
      )}

      {/* How to read legend */}
      <div className="panel-card">
        <div className="panel-card-title">How to Read the Graph</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {[
            { status: 'MASTERED', label: 'Mastered', desc: 'Solid understanding demonstrated' },
            { status: 'PARTIAL', label: 'Partial', desc: 'Emerging, has gaps' },
            { status: 'STRUGGLES_WITH', label: 'Struggling', desc: 'Persistent difficulty' },
            { status: 'MISCONCEPTION', label: 'Misconception', desc: 'Specific wrong belief (dashed ring)' },
            { status: 'UNSEEN', label: 'Unseen', desc: 'Neighbor context node' },
          ].map(({ status, label, desc }) => (
            <div key={status} style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
              <div style={{
                width: 9, height: 9, borderRadius: '50%', flexShrink: 0, marginTop: 3,
                background: {
                  MASTERED: 'var(--green)', PARTIAL: 'var(--yellow)',
                  STRUGGLES_WITH: 'var(--red)', MISCONCEPTION: 'var(--red)', UNSEEN: 'var(--border)',
                }[status]
              }} />
              <div>
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)' }}>{label}</span>
                <span style={{ fontSize: 10, color: 'var(--text-dim)', marginLeft: 4 }}>— {desc}</span>
              </div>
            </div>
          ))}
          <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-dim)', lineHeight: 1.6 }}>
            Arrows show prerequisite direction: A → B means A must be learned before B.
            Nodes positioned top (earlier grades) to bottom (later grades).
          </div>
        </div>
      </div>
    </div>
  )
}
