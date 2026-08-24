import { useState, useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import { Search, ZoomIn, ZoomOut, Maximize2, X, Network } from 'lucide-react'

export default function Graph() {
  const containerRef = useRef(null)
  const cyRef = useRef(null)
  const tooltipRef = useRef(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [activeTab, setActiveTab] = useState('storytelling')
  const [nodeDetail, setNodeDetail] = useState(null)
  const [filters, setFilters] = useState({
    Persona: true, Organizzazione: true, Procedura: true,
    Documento: true, Luogo: true, Concetto: true,
  })
  const [searchTerm, setSearchTerm] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Carica grafo dal backend
  useEffect(() => {
    async function loadGraph() {
      try {
        const res = await fetch('/api/graph')
        if (!res.ok) throw new Error(`${res.status}`)
        const data = await res.json()

        if (!data.nodes || data.nodes.length === 0) {
          setLoading(false)
          return
        }

        if (!containerRef.current || cyRef.current) return

        const cy = cytoscape({
          container: containerRef.current,
          elements: [
            ...data.nodes.map(n => ({
              data: { id: n.id, label: n.label, type: n.type },
            })),
            ...data.edges.map((e, i) => ({
              data: { id: `e${i}`, source: e.source, target: e.target, label: e.label },
            })),
          ],
          style: [
            {
              selector: 'node',
              style: {
                'label': 'data(label)',
                'text-valign': 'center', 'text-halign': 'center',
                'font-size': '10px', 'font-family': 'Plus Jakarta Sans, sans-serif',
                'color': '#F5F7FA',
                'text-outline-width': 2, 'text-outline-color': '#1A1F26',
                'background-color': 'data(typeColor)',
                'width': 40, 'height': 40,
                'border-width': 2, 'border-color': 'rgba(255, 215, 0, 0.15)',
              }
            },
            {
              selector: 'edge',
              style: {
                'width': 1.5, 'line-color': 'rgba(0, 168, 89, 0.25)',
                'target-arrow-color': 'rgba(0, 168, 89, 0.4)',
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier',
                'label': 'data(label)', 'font-size': '8px',
                'font-family': 'Plus Jakarta Sans, sans-serif',
                'color': '#6B7A8D', 'text-rotation': 'autorotate',
                'text-outline-width': 2, 'text-outline-color': '#1A1F26',
              }
            },
            { selector: 'node.highlighted', style: { 'border-width': 3, 'border-color': '#FFD700', 'width': 52, 'height': 52, 'z-index': 999 } },
            { selector: 'node.dimmed', style: { 'opacity': 0.15 } },
            { selector: 'edge.dimmed', style: { 'opacity': 0.05 } },
          ],
          layout: { name: 'cose', animate: true, animationDuration: 800, nodeRepulsion: 12000, idealEdgeLength: 100, gravity: 0.3 },
          userZoomingEnabled: true, userPanningEnabled: true, boxSelectionEnabled: false,
        })

        const TYPE_COLORS = { Organizzazione: '#00A859', Procedura: '#F5A623', Persona: '#3B9EFF', Documento: '#A78BFA', Luogo: '#FF6B6B', Concetto: '#9CA3AF' }
        cy.nodes().forEach(node => {
          const type = node.data('type')
          node.data('typeColor', TYPE_COLORS[type] || '#6B7A8D')
        })
        cy.style().update()

        // Tooltip
        cy.on('mouseover', 'node', (evt) => {
          const node = evt.target
          const tip = tooltipRef.current
          if (!tip) return
          tip.innerHTML = `<div class="graph-tooltip-type">${node.data('type')}</div><div class="graph-tooltip-label">${node.data('label')}</div><div class="graph-tooltip-meta">${node.degree()} relazioni</div>`
          tip.style.left = (evt.originalEvent.clientX + 14) + 'px'
          tip.style.top = (evt.originalEvent.clientY - 10) + 'px'
          tip.classList.add('visible')
        })
        cy.on('mouseout', 'node', () => tooltipRef.current?.classList.remove('visible'))
        cy.on('mousemove', (evt) => {
          const tip = tooltipRef.current
          if (tip?.classList.contains('visible')) {
            tip.style.left = (evt.originalEvent.clientX + 14) + 'px'
            tip.style.top = (evt.originalEvent.clientY - 10) + 'px'
          }
        })

        // Click nodo
        cy.on('tap', 'node', async (evt) => {
          const node = evt.target
          const nodeId = node.id()
          setSelectedNode(nodeId)
          setActiveTab('storytelling')
          cy.elements().removeClass('highlighted dimmed')
          node.addClass('highlighted')
          cy.elements().not(node.closedNeighborhood()).addClass('dimmed')

          // Carica dettagli dal backend
          try {
            const res = await fetch(`/api/graph/node/${nodeId}`)
            if (res.ok) {
              setNodeDetail(await res.json())
            }
          } catch {
            setNodeDetail({
              id: nodeId, label: node.data('label'), type: node.data('type'),
              degree: node.degree(), documents: [], storytelling: 'Dettagli non disponibili.', links: [],
            })
          }
        })

        cy.on('tap', () => {
          if (cy.target === cy) {
            setSelectedNode(null); setNodeDetail(null)
            cy.elements().removeClass('highlighted dimmed')
          }
        })

        cyRef.current = cy
        setLoading(false)
      } catch (e) {
        setError(e.message)
        setLoading(false)
      }
    }
    loadGraph()
  }, [])

  // Filtri per tipo
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().forEach(node => {
      node.style('display', filters[node.data('type')] !== false ? 'element' : 'none')
    })
  }, [filters])

  // Ricerca
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    if (!searchTerm.trim()) { cy.nodes().removeClass('highlighted dimmed'); return }
    const term = searchTerm.toLowerCase()
    cy.nodes().forEach(node => {
      const match = node.data('label').toLowerCase().includes(term)
      if (match) { node.addClass('highlighted'); node.removeClass('dimmed') }
      else { node.removeClass('highlighted'); node.addClass('dimmed') }
    })
    cy.edges().addClass('dimmed')
  }, [searchTerm])

  const handleZoomIn = () => cyRef.current?.zoom(cyRef.current.zoom() * 1.3)
  const handleZoomOut = () => cyRef.current?.zoom(cyRef.current.zoom() / 1.3)
  const handleFit = () => cyRef.current?.fit(undefined, 40)
  const handleCloseDetail = () => {
    setSelectedNode(null); setNodeDetail(null)
    cyRef.current?.elements().removeClass('highlighted dimmed')
  }
  const selectedNodeData = nodeDetail || (selectedNode ? (() => {
    const cy = cyRef.current; if (!cy) return null
    const n = cy.getElementById(selectedNode)
    return n ? { id: n.id(), label: n.data('label'), type: n.data('type') } : null
  })() : null)

  const TYPE_COLORS = { Organizzazione: '#00A859', Procedura: '#F5A623', Persona: '#3B9EFF', Documento: '#A78BFA', Luogo: '#FF6B6B', Concetto: '#9CA3AF' }

  return (
    <div className="animate-fade-in" aria-label="Knowledge Graph">
      <div className="graph-page-header">
        <h2>Knowledge Graph</h2>
        <p className="motto">Le informazioni acquistano valore quando sono collegate</p>
      </div>

      <div className="graph-layout">
        <aside className="graph-sidebar" aria-label="Filtri del grafo">
          <h3>Filtri</h3>
          <div className="graph-filter-group">
            <span className="graph-filter-label">Tipo entità</span>
            {Object.entries(TYPE_COLORS).map(([type, color]) => (
              <label key={type} className="graph-checkbox">
                <input type="checkbox" checked={filters[type] !== false}
                  onChange={e => setFilters(prev => ({ ...prev, [type]: e.target.checked }))} />
                <span style={{ color }}>{type}</span>
              </label>
            ))}
          </div>
          <div className="graph-filter-group">
            <span className="graph-filter-label">Cerca nodo</span>
            <div style={{ position: 'relative' }}>
              <Search size={14} style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input type="text" className="graph-search" placeholder="Cerca entità..." value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)} style={{ paddingLeft: '32px' }} aria-label="Cerca entità" />
            </div>
          </div>
        </aside>

        <div className="graph-canvas-wrap" role="img" aria-label="Grafo delle entità">
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)' }}>
              Caricamento grafo...
            </div>
          ) : error ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--jeeg-red)', textAlign: 'center', padding: '2rem' }}>
              <Network size={32} style={{ display: 'block', margin: '0 auto 1rem', opacity: 0.5 }} />
              <p>{error}</p>
            </div>
          ) : !cyRef.current ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)' }}>
              <Network size={40} style={{ display: 'block', margin: '0 auto 1rem', opacity: 0.15 }} />
              <p style={{ fontSize: 'var(--text-sm)' }}>Il grafo verrà generato al caricamento dei documenti.</p>
            </div>
          ) : (
            <>
              <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
              <div className="graph-zoom-controls">
                <button className="graph-zoom-btn" onClick={handleZoomIn} aria-label="Zoom in">+</button>
                <button className="graph-zoom-btn" onClick={handleZoomOut} aria-label="Zoom out">−</button>
                <button className="graph-zoom-btn" onClick={handleFit} aria-label="Adatta alla vista"><Maximize2 size={16} /></button>
              </div>
              <div className={`graph-status-bar ${selectedNodeData ? 'visible' : ''}`} aria-live="polite">
                <span>Nodo: <strong>{selectedNodeData?.label}</strong> ({selectedNodeData?.type}) · {selectedNodeData?.degree || 0} relazioni</span>
                <div className="graph-status-actions">
                  <button className="graph-status-btn">Apri fonti</button>
                  <button className="graph-status-btn">Vedi in Wiki</button>
                </div>
              </div>
              <div className={`graph-node-detail ${selectedNode ? 'open' : ''}`} role="dialog" aria-label={`Dettagli di ${selectedNodeData?.label}`}>
                <div className="graph-detail-header">
                  <div>
                    <div className="graph-detail-title">{selectedNodeData?.label}</div>
                    <div className="graph-detail-type">{selectedNodeData?.type}</div>
                  </div>
                  <button className="graph-detail-close" onClick={handleCloseDetail} aria-label="Chiudi dettagli"><X size={16} /></button>
                </div>
                <div className="graph-detail-tabs" role="tablist">
                  {['storytelling', 'collegamenti', 'narrazione visiva'].map(tab => (
                    <button key={tab} className={`graph-detail-tab ${activeTab === tab ? 'active' : ''}`}
                      onClick={() => setActiveTab(tab)} role="tab" aria-selected={activeTab === tab}>
                      {tab.charAt(0).toUpperCase() + tab.slice(1)}
                    </button>
                  ))}
                </div>
                <div className="graph-detail-body" role="tabpanel">
                  {activeTab === 'storytelling' && <p>{nodeDetail?.storytelling || 'Seleziona un nodo.'}</p>}
                  {activeTab === 'collegamenti' && (
                    <>
                      <h4>Relazioni ({nodeDetail?.links?.length || 0})</h4>
                      {nodeDetail?.links?.length > 0 ? (
                        <ul className="graph-link-list">
                          {nodeDetail.links.map((link, i) => (
                            <li key={i} className="graph-link-item">
                              <span className="graph-link-relation">{link.relation}</span>
                              <span className="graph-link-target">{link.target}</span>
                            </li>
                          ))}
                        </ul>
                      ) : <p style={{ color: 'var(--text-muted)' }}>Nessuna relazione.</p>}
                    </>
                  )}
                  {activeTab === 'narrazione visiva' && (
                    <div>
                      <h4>Contesto visivo</h4>
                      <p>Il nodo <strong>{selectedNodeData?.label}</strong> è collegato a {nodeDetail?.links?.length || 0} entità.
                        {nodeDetail?.links?.length > 0 && (<> Le relazioni principali: {nodeDetail.links.slice(0, 3).map(l => `"${l.relation}"`).join(', ')}.</>)}
                      </p>
                      <p style={{ color: 'var(--text-muted)', marginTop: '1rem', fontSize: 'var(--text-xs)' }}>
                        I nodi connessi sono evidenziati nel grafo con bordo dorato. Usa i controlli di zoom per esplorare.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
      <div ref={tooltipRef} className="graph-tooltip" role="tooltip" />
    </div>
  )
}