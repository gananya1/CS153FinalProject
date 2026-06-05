import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'

const STATUS_COLOR = {
  MASTERED: '#34d399',
  PARTIAL: '#fbbf24',
  STRUGGLES_WITH: '#f87171',
  MISCONCEPTION: '#f87171',
  UNSEEN: '#2a3349',
}
const STATUS_STROKE = {
  MASTERED: '#059669',
  PARTIAL: '#d97706',
  STRUGGLES_WITH: '#dc2626',
  MISCONCEPTION: '#dc2626',
  UNSEEN: '#3a4460',
}

export default function KnowledgeGraph({ graphData, onNodeClick, selectedNode }) {
  const svgRef = useRef(null)
  const [tooltip, setTooltip] = useState(null)

  // Main simulation effect — only reruns when node count changes
  useEffect(() => {
    if (!graphData || !graphData.nodes.length) return
    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const rect = svgRef.current.getBoundingClientRect()
    const W = rect.width || 800
    const H = rect.height || 600

    const zoom = d3.zoom().scaleExtent([0.2, 3]).on('zoom', (e) => {
      g.attr('transform', e.transform)
    })
    svg.call(zoom)

    const g = svg.append('g')

    // Filter to seen nodes + immediate neighbors for clarity
    const seenIds = new Set(
      graphData.nodes.filter(n => n.status !== 'UNSEEN').map(n => n.id)
    )
    const relevantIds = new Set(seenIds)
    graphData.edges.forEach(e => {
      if (seenIds.has(e.source) || seenIds.has(e.target)) {
        relevantIds.add(e.source)
        relevantIds.add(e.target)
      }
    })

    const nodes = graphData.nodes
      .filter(n => relevantIds.has(n.id))
      .map(n => ({ ...n }))
    const nodeIds = new Set(nodes.map(n => n.id))

    const links = graphData.edges
      .filter(e => nodeIds.has(e.source) && nodeIds.has(e.target) && e.type === 'PREREQUISITE_OF')
      .map(e => ({ ...e }))

    // Arrowhead marker
    svg.append('defs').append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -4 8 8')
      .attr('refX', 16)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L8,0L0,4')
      .attr('fill', '#3a4460')

    const gradeOrder = { 'K': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, 'HS': 9 }
    const maxGrade = Math.max(...nodes.map(n => gradeOrder[n.grade] ?? 5))

    // Force simulation — tuned for stability
    const sim = d3.forceSimulation(nodes)
      .alphaDecay(0.05)
      .velocityDecay(0.6)
      .force('link', d3.forceLink(links).id(d => d.id).distance(90).strength(0.8))
      .force('charge', d3.forceManyBody().strength(-120))
      .force('center', d3.forceCenter(W / 2, H / 2).strength(0.05))
      .force('y', d3.forceY(d => {
        const gr = gradeOrder[d.grade] ?? 5
        return (gr / (maxGrade || 1)) * H * 0.8 + H * 0.1
      }).strength(0.4))
      .force('collision', d3.forceCollide(28))

    // Links
    const link = g.append('g').selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', '#2a3349')
      .attr('stroke-width', 1.5)
      .attr('marker-end', 'url(#arrow)')
      .attr('opacity', 0.7)

    // Node groups
    const node = g.append('g').selectAll('g')
      .data(nodes)
      .join('g')
      .attr('cursor', 'pointer')
      .call(d3.drag()
        .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.1).restart(); d.fx = d.x; d.fy = d.y })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y })
        .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null })
      )
      .on('click', (e, d) => { onNodeClick && onNodeClick(d) })
      .on('mousemove', (e, d) => setTooltip({ x: e.clientX + 12, y: e.clientY - 10, node: d }))
      .on('mouseleave', () => setTooltip(null))

    // Node circles
    node.append('circle')
      .attr('r', d => d.status !== 'UNSEEN' ? 14 : 10)
      .attr('fill', d => STATUS_COLOR[d.status] || STATUS_COLOR.UNSEEN)
      .attr('stroke', d => STATUS_STROKE[d.status] || STATUS_STROKE.UNSEEN)
      .attr('stroke-width', 1.5)
      .attr('opacity', d => d.status === 'UNSEEN' ? 0.4 : 1)

    // Misconception ring
    node.filter(d => d.status === 'MISCONCEPTION')
      .append('circle')
      .attr('r', 18)
      .attr('fill', 'none')
      .attr('stroke', '#f87171')
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '3,2')
      .attr('opacity', 0.6)

    // Labels
    node.append('text')
      .text(d => d.id)
      .attr('text-anchor', 'middle')
      .attr('dy', 26)
      .attr('font-size', '9px')
      .attr('font-family', 'DM Mono, monospace')
      .attr('fill', d => d.status === 'UNSEEN' ? '#4a5568' : '#8892a4')
      .attr('pointer-events', 'none')

    sim.on('tick', () => {
      link
        .attr('x1', d => d.source.x)
        .attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x)
        .attr('y2', d => d.target.y)
      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })

    // Initial zoom to fit
    setTimeout(() => {
      const bounds = g.node().getBBox()
      if (bounds.width && bounds.height) {
        const scale = Math.min(0.9, Math.min(W / bounds.width, H / bounds.height) * 0.85)
        const tx = W / 2 - scale * (bounds.x + bounds.width / 2)
        const ty = H / 2 - scale * (bounds.y + bounds.height / 2)
        svg.call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(scale))
      }
    }, 800)

    return () => sim.stop()
  }, [graphData?.nodes?.length])

  // Lightweight selected node highlight — no simulation restart
  useEffect(() => {
    if (!svgRef.current) return
    d3.select(svgRef.current).selectAll('circle')
      .attr('stroke', function(d) {
        if (!d) return null
        if (selectedNode && d.id === selectedNode.id) return '#f59e0b'
        return STATUS_STROKE[d.status] || STATUS_STROKE.UNSEEN
      })
      .attr('stroke-width', function(d) {
        if (!d) return null
        return selectedNode && d.id === selectedNode.id ? 3 : 1.5
      })
  }, [selectedNode])

  if (!graphData || !graphData.nodes.length) {
    return (
      <div className="graph-empty">
        <div style={{ fontSize: 32, opacity: 0.3 }}>◎</div>
        <div>No graph data yet — start a tutoring session</div>
      </div>
    )
  }

  return (
    <>
      <svg ref={svgRef} className="graph-canvas" style={{ display: 'block', width: '100%', height: '100%' }} />
      {tooltip && (
        <div className="tooltip" style={{ left: tooltip.x, top: tooltip.y }}>
          <div className="tooltip-id">{tooltip.node.id}</div>
          <div className="tooltip-desc">{tooltip.node.description?.slice(0, 100)}{tooltip.node.description?.length > 100 ? '…' : ''}</div>
          {tooltip.node.status !== 'UNSEEN' && (
            <div style={{ marginTop: 4, fontSize: 10, color: STATUS_COLOR[tooltip.node.status] }}>
              {tooltip.node.status} · {(tooltip.node.confidence * 100).toFixed(0)}%
            </div>
          )}
        </div>
      )}
    </>
  )
}
