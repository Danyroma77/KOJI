/**
 * =============================================================================
 * PAGINA WIKI — WIKI SEMANTICA GENERATA
 * =============================================================================
 * 
 * Visualizzazione della wiki generata automaticamente dai documenti della KB.
 * 
 * FUNZIONALITÀ:
 * - Indice navigabile per categorie (Regolamenti, Circolari, Procedure, FAQ, Altro)
 * - Ricerca pagine per nome
 * - Visualizzazione contenuto Markdown con react-markdown
 * - Fonti citate per ogni pagina
 * - Aggiornamento automatico quando si rigenera la wiki
 * 
 * STRUTTURA:
 * - Indice: gruppi di pagine con conteggio
 * - Pagine: contenuto Markdown con titolo, corpo e fonti
 * 
 * CATEGORIE (generate automaticamente):
 * - Regolamenti: file con "regolament" nel nome
 * - Circolari: file con "circolar" nel nome
 * - Procedure: file con "procedur" o "manuale" nel nome
 * - FAQ: file con "faq" nel nome
 * - Altro: tutto il resto
 */

import { useState, useEffect, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChevronRight, Search, BookOpen, FileText, X, Loader2 } from 'lucide-react'

export default function Wiki() {
  const [index, setIndex] = useState({ groups: [] })
  const [activePage, setActivePage] = useState(null)
  const [pageContent, setPageContent] = useState(null)
  const [pageLoading, setPageLoading] = useState(false)
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
      setPageLoading(true)
      try {
        const res = await fetch(`/api/wiki/page/${activePage}`)
        if (!res.ok) throw new Error()
        setPageContent(await res.json())
      } catch {
        setPageContent(null)
      } finally {
        setPageLoading(false)
      }
    }
    loadPage()
  }, [activePage])

  function toggleGroup(idx) {
    setOpenGroups(prev => ({ ...prev, [idx]: !prev[idx] }))
  }

  // Filtro ricerca sull'indice (uso useMemo: l'oggetto va ricomputato solo
  // al cambio di indice/termine e il check "vuoto" e' su .groups, non .length)
  const filteredIndex = useMemo(() => {
    if (!searchTerm.trim()) return index
    const term = searchTerm.toLowerCase()
    return {
      groups: (index.groups || [])
        .map(g => ({
          ...g,
          items: (g.items || []).filter(item => item.label.toLowerCase().includes(term)),
        }))
        .filter(g => g.items.length > 0),
    }
  }, [index, searchTerm])

  const totalPages = useMemo(
    () => (index.groups || []).reduce((n, g) => n + (g.items?.length || 0), 0),
    [index]
  )
  const searchResults = useMemo(
    () => (filteredIndex.groups || []).reduce((n, g) => n + g.items.length, 0),
    [filteredIndex]
  )

  return (
    <div className="animate-fade-in" aria-label="Wiki semantica">
      <div className="wiki-header">
        <div>
          <h2>Wiki semantica</h2>
          <p className="motto">La conoscenza diventa navigabile</p>
        </div>
        <div className="wiki-header-tools">
          {totalPages > 0 && (
            <span className="wiki-count">{totalPages} pagine</span>
          )}
          <div className="wiki-search-wrap">
            <Search size={14} aria-hidden="true" className="wiki-search-icon" />
            <input
              type="text"
              className="wiki-search"
              placeholder="Cerca una pagina…"
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              aria-label="Cerca una pagina nella wiki"
            />
            {searchTerm && (
              <button
                type="button"
                className="wiki-search-clear"
                onClick={() => setSearchTerm('')}
                aria-label="Cancella la ricerca"
              >
                <X size={13} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="wiki-layout">
        {/* Indice */}
        <nav className="wiki-index" aria-label="Indice della wiki">
          <div className="wiki-index-head">
            <h3>Indice</h3>
            {searchTerm && (
              <span className="wiki-index-results" role="status">
                {searchResults} risultati
              </span>
            )}
          </div>
          {loading ? (
            <div className="wiki-empty" role="status">
              <Loader2 size={22} aria-hidden="true" className="wiki-spinner" />
              <p>Caricamento indice…</p>
            </div>
          ) : filteredIndex.groups.length === 0 ? (
            <div className="wiki-empty">
              <BookOpen size={28} aria-hidden="true" />
              <p>
                {searchTerm
                  ? <>Nessun risultato per «{searchTerm}»</>
                  : 'La wiki viene generata automaticamente al caricamento dei documenti.'}
              </p>
            </div>
          ) : (
            filteredIndex.groups.map((group, gi) => (
              <div key={gi} className="wiki-index-group">
                <button
                  type="button"
                  className={`wiki-index-group-title ${openGroups[gi] ? 'open' : ''}`}
                  onClick={() => toggleGroup(gi)}
                  aria-expanded={openGroups[gi]}
                >
                  <ChevronRight size={14} aria-hidden="true" />
                  {group.title}
                  <span className="wiki-index-group-count">{group.items.length}</span>
                </button>
                {openGroups[gi] && (
                  <div className="wiki-index-items">
                    {group.items.map(item => (
                      <button
                        key={item.id}
                        type="button"
                        className={`wiki-index-item ${activePage === item.id ? 'active' : ''}`}
                        onClick={() => setActivePage(item.id)}
                        aria-current={activePage === item.id ? 'page' : undefined}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </nav>

        {/* Contenuto */}
        <article
          className="wiki-content"
          aria-label="Pagina wiki"
          aria-busy={pageLoading}
        >
          {!activePage ? (
            <div className="wiki-empty wiki-empty-lg">
              <BookOpen size={40} aria-hidden="true" />
              <p className="wiki-empty-title">Seleziona una voce dall'indice</p>
              <p className="wiki-empty-sub">
                oppure carica documenti per generare automaticamente la wiki.
              </p>
            </div>
          ) : pageLoading ? (
            <div className="wiki-empty" role="status">
              <Loader2 size={22} aria-hidden="true" className="wiki-spinner" />
              <p>Caricamento pagina…</p>
            </div>
          ) : !pageContent ? (
            <div className="wiki-empty" role="alert">
              <BookOpen size={28} aria-hidden="true" />
              <p>Impossibile caricare la pagina. Riprova.</p>
            </div>
          ) : (
            <>
              <header className="wiki-page-head">
                <h1>{pageContent.title}</h1>
              </header>
              <div className="wiki-md">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {pageContent.content}
                </ReactMarkdown>
              </div>
              {pageContent.sources && pageContent.sources.length > 0 && (
                <footer className="wiki-sources" aria-label="Fonti della pagina">
                  <span className="wiki-sources-label">Fonti</span>
                  <ul className="wiki-sources-list">
                    {pageContent.sources.map((s, i) => (
                      <li key={i} className="wiki-source-item">
                        <FileText size={13} aria-hidden="true" />
                        <span>{s}</span>
                      </li>
                    ))}
                  </ul>
                </footer>
              )}
            </>
          )}
        </article>
      </div>
    </div>
  )
}