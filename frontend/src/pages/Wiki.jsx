import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChevronRight, Search, BookOpen } from 'lucide-react'

export default function Wiki() {
  const [index, setIndex] = useState({ groups: [] })
  const [activePage, setActivePage] = useState(null)
  const [pageContent, setPageContent] = useState(null)
  const [openGroups, setOpenGroups] = useState({})
  const [searchTerm, setSearchTerm] = useState('')
  const [loading, setLoading] = useState(true)

  // Carica indice
  useEffect(() => {
    async function loadIndex() {
      try {
        const res = await fetch('/api/wiki/index')
        if (!res.ok) throw new Error()
        const data = await res.json()
        setIndex(data)
        // Apri il primo gruppo di default
        const open = {}
        if (data.groups && data.groups.length > 0) open[0] = true
        setOpenGroups(open)
      } catch {
        setIndex({ groups: [] })
      } finally {
        setLoading(false)
      }
    }
    loadIndex()
  }, [])

  // Carica pagina selezionata
  useEffect(() => {
    if (!activePage) {
      setPageContent(null)
      return
    }
    async function loadPage() {
      try {
        const res = await fetch(`/api/wiki/page/${activePage}`)
        if (!res.ok) throw new Error()
        const data = await res.json()
        setPageContent(data)
      } catch {
        setPageContent(null)
      }
    }
    loadPage()
  }, [activePage])

  function toggleGroup(idx) {
    setOpenGroups(prev => ({ ...prev, [idx]: !prev[idx] }))
  }

  // Filtro ricerca sull'indice
  const filteredIndex = searchTerm.trim()
    ? {
        groups: index.groups.map(g => ({
          ...g,
          items: g.items.filter(item =>
            item.label.toLowerCase().includes(searchTerm.toLowerCase())
          ),
        })).filter(g => g.items.length > 0),
      }
    : index.groups

  return (
    <div className="animate-fade-in" aria-label="Wiki semantica">
      <div className="wiki-header">
        <div>
          <h2>Wiki semantica</h2>
          <p className="motto">La conoscenza diventa navigabile</p>
        </div>
        <div style={{ position: 'relative' }}>
          <Search size={14} style={{
            position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)',
            color: 'var(--text-muted)'
          }} />
          <input
            type="text"
            className="wiki-search"
            placeholder="Cerca nella wiki..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            style={{ paddingLeft: '34px' }}
            aria-label="Cerca nella wiki"
          />
        </div>
      </div>

      <div className="wiki-layout">
        {/* Indice */}
        <nav className="wiki-index" aria-label="Indice della wiki">
          <h3>Indice</h3>
          {loading ? (
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>Caricamento...</p>
          ) : filteredIndex.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '2rem 0' }}>
              <BookOpen size={28} style={{ display: 'block', margin: '0 auto 0.8rem', opacity: 0.25 }} />
              <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', lineHeight: 1.5 }}>
                {searchTerm
                  ? 'Nessun risultato per questa ricerca'
                  : 'La wiki verrà generata automaticamente al caricamento dei documenti.'}
              </p>
            </div>
          ) : (
            filteredIndex.map((group, gi) => (
              <div key={gi} className="wiki-index-group">
                <button
                  className={`wiki-index-group-title ${openGroups[gi] ? 'open' : ''}`}
                  onClick={() => toggleGroup(gi)}
                  aria-expanded={openGroups[gi]}
                >
                  <ChevronRight size={14} aria-hidden="true" />
                  {group.title}
                  <span style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', fontWeight: 400 }}>
                    {group.items.length}
                  </span>
                </button>
                {openGroups[gi] && (
                  <div className="wiki-index-items" role="list">
                    {group.items.map(item => (
                      <a
                        key={item.id}
                        className={`wiki-index-item ${activePage === item.id ? 'active' : ''}`}
                        onClick={() => setActivePage(item.id)}
                        role="listitem"
                        tabIndex={0}
                        aria-current={activePage === item.id ? 'page' : undefined}
                      >
                        {item.label}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </nav>

        {/* Contenuto */}
        <article className="wiki-content" aria-label="Pagina wiki">
          {!activePage ? (
            <div style={{ textAlign: 'center', padding: '4rem 1rem', color: 'var(--text-muted)' }}>
              <BookOpen size={40} style={{ display: 'block', margin: '0 auto 1rem', opacity: 0.2 }} />
              <p style={{ fontSize: 'var(--text-lg)', marginBottom: '0.5rem' }}>Seleziona una voce dall'indice</p>
              <p style={{ fontSize: 'var(--text-sm)' }}>oppure carica documenti per generare automaticamente la wiki.</p>
            </div>
          ) : !pageContent ? (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-muted)' }}>
              Caricamento...
            </div>
          ) : (
            <>
              <h1>{pageContent.title}</h1>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {pageContent.content}
              </ReactMarkdown>
              {pageContent.sources && pageContent.sources.length > 0 && (
                <div className="wiki-sources">
                  <strong>Fonti:</strong>{' '}
                  {pageContent.sources.join(' · ')}
                </div>
              )}
            </>
          )}
        </article>
      </div>
    </div>
  )
}