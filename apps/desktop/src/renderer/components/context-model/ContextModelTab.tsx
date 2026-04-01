import { useEffect, useRef, useState, useCallback } from 'react'
import { useProjectStore } from '../../stores/projectStore'
import * as d3 from 'd3'
import { X, Zap } from 'lucide-react'

const TYPE_COLORS: Record<string, string> = {
  software_module: '#3b82f6',
  electrical_part: '#22c55e',
  mechanical_part: '#f97316',
  interface: '#a855f7',
  document: '#64748b',
  runtime_signal: '#06b6d4',
  simulation_asset: '#ec4899',
}

interface GNode extends d3.SimulationNodeDatum {
  id: string
  entity_type: string
  name: string
  description: string
  metadata: any
  source: string
  source_ref: string
  connectionCount: number
}

interface GLink extends d3.SimulationLinkDatum<GNode> {
  id: string
  relation_type: string
  confidence: number
}

export default function ContextModelTab() {
  const store = useProjectStore()
  const pid = store.currentProjectId
  const svgRef = useRef<SVGSVGElement>(null)
  const simRef = useRef<d3.Simulation<GNode, GLink> | null>(null)
  const [selected, setSelected] = useState<GNode | null>(null)
  const [impactResult, setImpactResult] = useState<any>(null)
  const [impactedIds, setImpactedIds] = useState<Set<string>>(new Set())
  const [anomalyIds, setAnomalyIds] = useState<Set<string>>(new Set())
  const [connections, setConnections] = useState<{ type: string; names: string[] }[]>([])
  const nodesRef = useRef<GNode[]>([])
  const linksRef = useRef<GLink[]>([])

  useEffect(() => {
    store.fetchGraph(pid)
  }, [pid])

  // Anomaly polling
  useEffect(() => {
    let zeroSince = 0
    const iv = setInterval(async () => {
      try {
        const res = await fetch(`/api/projects/${pid}/live-bench/state`)
        const data = await res.json()
        if (data.anomaly_count > 0) {
          zeroSince = 0
          const ids = new Set<string>()
          for (const n of nodesRef.current) {
            const nm = (n.name + ' ' + JSON.stringify(n.metadata)).toLowerCase()
            if (nm.includes('motor') || nm.includes('tb6612')) ids.add(n.id)
          }
          setAnomalyIds(ids)
        } else {
          if (zeroSince === 0) zeroSince = Date.now()
          if (Date.now() - zeroSince > 10000) setAnomalyIds(new Set())
        }
      } catch { /* backend not running */ }
    }, 5000)
    return () => clearInterval(iv)
  }, [pid])

  // Build graph
  useEffect(() => {
    if (!svgRef.current) return
    const entities = store.entities
    const relations = store.relations
    if (entities.length === 0) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const width = svgRef.current.clientWidth
    const height = svgRef.current.clientHeight

    const entityIds = new Set(entities.map((e: any) => e.id))
    const connCount: Record<string, number> = {}
    const validLinks: GLink[] = []
    for (const r of relations) {
      if (entityIds.has(r.source_entity_id) && entityIds.has(r.target_entity_id)) {
        validLinks.push({
          id: r.id,
          source: r.source_entity_id,
          target: r.target_entity_id,
          relation_type: r.relation_type,
          confidence: r.confidence ?? 1,
        })
        connCount[r.source_entity_id] = (connCount[r.source_entity_id] || 0) + 1
        connCount[r.target_entity_id] = (connCount[r.target_entity_id] || 0) + 1
      }
    }

    const nodes: GNode[] = entities.map((e: any) => ({
      id: e.id,
      entity_type: e.entity_type,
      name: e.name,
      description: e.description || '',
      metadata: e.metadata || {},
      source: e.source || '',
      source_ref: e.source_ref || '',
      connectionCount: connCount[e.id] || 0,
    }))

    nodesRef.current = nodes
    linksRef.current = validLinks

    // Arrow marker
    svg.append('defs').append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '0 -3 6 6')
      .attr('refX', 18)
      .attr('refY', 0)
      .attr('markerWidth', 5)
      .attr('markerHeight', 5)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-3L6,0L0,3')
      .attr('fill', '#2a2a3a')

    const g = svg.append('g')

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 5])
      .on('zoom', (event) => g.attr('transform', event.transform))
    svg.call(zoom)

    const link = g.append('g')
      .selectAll('line')
      .data(validLinks)
      .join('line')
      .attr('stroke', '#2a2a3a')
      .attr('stroke-width', 1)
      .attr('stroke-opacity', (d) => d.confidence)
      .attr('marker-end', 'url(#arrowhead)')

    const node = g.append('g')
      .selectAll<SVGCircleElement, GNode>('circle')
      .data(nodes)
      .join('circle')
      .attr('r', (d) => 8 + Math.sqrt(d.connectionCount) * 3)
      .attr('fill', (d) => TYPE_COLORS[d.entity_type] || '#64748b')
      .attr('stroke', '#0a0a0f')
      .attr('stroke-width', 1.5)
      .attr('cursor', 'pointer')
      .on('click', (_event, d) => {
        setSelected(d)
        setImpactResult(null)
        const conns: Record<string, string[]> = {}
        for (const l of validLinks) {
          const srcId = typeof l.source === 'object' ? (l.source as GNode).id : l.source
          const tgtId = typeof l.target === 'object' ? (l.target as GNode).id : l.target
          if (srcId === d.id) {
            const tgt = nodes.find(n => n.id === tgtId)
            if (tgt) {
              conns[l.relation_type] = conns[l.relation_type] || []
              conns[l.relation_type].push(tgt.name)
            }
          } else if (tgtId === d.id) {
            const src = nodes.find(n => n.id === srcId)
            if (src) {
              conns[l.relation_type] = conns[l.relation_type] || []
              conns[l.relation_type].push(src.name)
            }
          }
        }
        setConnections(Object.entries(conns).map(([type, names]) => ({ type, names })))
      })
      .call(d3.drag<SVGCircleElement, GNode>()
        .on('start', (event, d) => {
          if (!event.active) sim.alphaTarget(0.3).restart()
          d.fx = d.x; d.fy = d.y
        })
        .on('drag', (event, d) => {
          d.fx = event.x; d.fy = event.y
        })
        .on('end', (event, d) => {
          if (!event.active) sim.alphaTarget(0)
          d.fx = null; d.fy = null
        })
      )

    const label = g.append('g')
      .selectAll('text')
      .data(nodes)
      .join('text')
      .text((d) => d.name.length > 20 ? d.name.slice(0, 18) + '..' : d.name)
      .attr('font-family', "'JetBrains Mono', monospace")
      .attr('font-size', '9px')
      .attr('fill', '#94a3b8')
      .attr('dx', 14)
      .attr('dy', 3)
      .attr('pointer-events', 'none')

    const sim = d3.forceSimulation<GNode>(nodes)
      .force('link', d3.forceLink<GNode, GLink>(validLinks).id(d => d.id).distance(80))
      .force('charge', d3.forceManyBody().strength(-250))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide(20))
      .on('tick', () => {
        link
          .attr('x1', (d: any) => d.source.x)
          .attr('y1', (d: any) => d.source.y)
          .attr('x2', (d: any) => d.target.x)
          .attr('y2', (d: any) => d.target.y)
        node.attr('cx', d => d.x!).attr('cy', d => d.y!)
        label.attr('x', d => d.x!).attr('y', d => d.y!)
      })

    simRef.current = sim

    return () => { sim.stop() }
  }, [store.entities, store.relations])

  // Update node styles for impact/anomaly highlighting
  useEffect(() => {
    if (!svgRef.current) return
    const svg = d3.select(svgRef.current)
    svg.selectAll<SVGCircleElement, GNode>('circle')
      .attr('fill', (d) => {
        if (impactedIds.has(d.id)) return '#ef4444'
        if (anomalyIds.has(d.id)) return '#ef4444'
        return TYPE_COLORS[d.entity_type] || '#64748b'
      })
      .attr('filter', (d) => {
        if (anomalyIds.has(d.id)) return 'drop-shadow(0 0 6px #ef4444)'
        if (impactedIds.has(d.id)) return 'drop-shadow(0 0 4px #ef4444)'
        return ''
      })
  }, [impactedIds, anomalyIds])

  const handleImpact = useCallback(async () => {
    if (!selected) return
    try {
      const res = await fetch(`/api/projects/${pid}/impact/${selected.id}`)
      const data = await res.json()
      setImpactResult(data)
      setImpactedIds(new Set((data.impacted || []).map((i: any) => i.entity_id)))
    } catch { /* */ }
  }, [selected, pid])

  return (
    <div className="relative flex h-full w-full overflow-hidden">
      <style>{`
        @keyframes pulse-red { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
        .pulse-impact { animation: pulse-red 1.5s ease-in-out infinite; }
      `}</style>
      <svg ref={svgRef} className="flex-1 h-full bg-solus-bg" />

      {/* Legend */}
      <div className="absolute top-3 left-3 bg-solus-surface/90 border border-solus-border rounded-lg p-2.5 space-y-1">
        {Object.entries(TYPE_COLORS).map(([type, color]) => (
          <div key={type} className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
            <span className="text-[9px] font-mono text-solus-text-muted">{type.replace(/_/g, ' ')}</span>
          </div>
        ))}
      </div>

      {/* Detail panel */}
      {selected && (
        <div className="w-80 bg-solus-surface border-l border-solus-border overflow-y-auto p-4 space-y-4 transition-all">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="text-lg font-bold text-solus-text">{selected.name}</h3>
              <div className="flex items-center gap-1.5 mt-1">
                <div className="w-2.5 h-2.5 rounded-full" style={{ background: TYPE_COLORS[selected.entity_type] || '#64748b' }} />
                <span className="text-[10px] font-mono text-solus-text-dim">{selected.entity_type.replace(/_/g, ' ')}</span>
              </div>
            </div>
            <button onClick={() => { setSelected(null); setImpactResult(null); setImpactedIds(new Set()) }}
              className="text-solus-text-muted hover:text-solus-text p-1"><X size={14} /></button>
          </div>

          {selected.description && (
            <p className="text-sm text-solus-text-dim leading-relaxed">{selected.description}</p>
          )}

          {/* Metadata */}
          {Object.keys(selected.metadata).length > 0 && (
            <div>
              <h4 className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted mb-1.5">Metadata</h4>
              <table className="w-full text-xs font-mono">
                <tbody>
                  {Object.entries(selected.metadata)
                    .filter(([k]) => k !== 'file_content')
                    .map(([k, v]) => (
                      <tr key={k} className="border-t border-solus-border/50">
                        <td className="py-1 pr-2 text-solus-text-muted align-top">{k}</td>
                        <td className="py-1 text-solus-text break-all">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Connections */}
          {connections.length > 0 && (
            <div>
              <h4 className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted mb-1.5">Connections</h4>
              <div className="space-y-1">
                {connections.map(c => (
                  <div key={c.type} className="text-xs">
                    <span className="font-mono text-solus-accent-bright capitalize">{c.type.replace(/_/g, ' ')}: </span>
                    <span className="text-solus-text-dim">{c.names.join(', ')}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Impact */}
          <button onClick={handleImpact}
            className="w-full flex items-center justify-center gap-1.5 bg-solus-accent/15 hover:bg-solus-accent/25 text-solus-accent-bright text-xs font-mono py-2 rounded transition-colors">
            <Zap size={12} /> Impact Analysis
          </button>

          {impactResult && (
            <div>
              <h4 className="text-[10px] font-mono font-semibold uppercase tracking-widest text-solus-text-muted mb-1.5">
                Impacted ({impactResult.total_impacted})
              </h4>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {(impactResult.impacted || []).map((imp: any) => (
                  <div key={imp.entity_id} className="flex items-center gap-1.5 text-xs">
                    <div className="w-2 h-2 rounded-full bg-red-500 pulse-impact" />
                    <span className="font-mono text-solus-text">{imp.entity_name}</span>
                    <span className="text-solus-text-muted">depth {imp.depth}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
