/**
 * =============================================================================
 * PAGINA RAG — INTERROGAZIONE KNOWLEDGE BASE
 * =============================================================================
 * 
 * Interfaccia per interrogare la Knowledge Base tramite RAG con streaming SSE.
 * 
 * FUNZIONALITÀ:
 * - Chat interattiva con risposte in tempo reale
 * - Visualizzazione fonti citate con punteggi
 * - Metriche live (tok/s, TTFT, latency)
 * - Selezione modello e modalità di retrieval
 * - Copia metriche in formato Markdown per tesi
 * 
 * FLUSSO:
 * 1. Utente inserisce domanda
 * 2. Invio a /api/rag/query con SSE
 * 3. Ricezione eventi: status, sources, token, metrics, done
 * 4. Visualizzazione progressiva della risposta
 * 
 * METRICHE:
 * - Ricerca: tempo recupero documenti (ms)
 * - Throughput: token al secondo
 * - TTFT: Time To First Token (ms)
 * - Token: numero totale generati
 */

import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Send, Settings, Copy, Check, User, Trash2 } from 'lucide-react'

export default function RAG() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [sources, setSources] = useState([])
  // Metriche live durante lo streaming (stimate dal client) e confermate
  // dal backend a fine risposta con i valori autorevoli
  const [metrics, setMetrics] = useState({
    tokPerSec: '—', ttft: '—', tokens: '—', retrieval: '—', live: false,
  })
  // Annuncio per screen reader a fine generazione (regione live)
  const [announce, setAnnounce] = useState('')
  // Fase corrente comunicata dal backend (status SSE): ricerca/generazione
  const [stage, setStage] = useState('')
  // Avviso quando il retrieval non trova documenti (status SSE con empty=true)
  const [emptyNotice, setEmptyNotice] = useState('')
  const [activeModel, setActiveModel] = useState(null)
  const [retrievalMode, setRetrievalMode] = useState('hybrid')
  // null = verifica in corso, false = KB vuota, true = almeno un documento pronto
  const [kbReady, setKbReady] = useState(null)
  const [copiedMetrics, setCopiedMetrics] = useState(false)
  const [viewingDoc, setViewingDoc] = useState(null)
  const messagesEndRef = useRef(null)
  // Contatori per le metriche live: aggiornati ad ogni token senza re-render
  const tokenCountRef = useRef(0)
  const firstTokenAtRef = useRef(0)
  const genStartRef = useRef(0)
  const metricsTimerRef = useRef(null)
  const navigate = useNavigate()

  // Pulizia del timer delle metriche live allo smontaggio
  useEffect(() => () => clearInterval(metricsTimerRef.current), [])

  // Modello attivo (sola lettura): la scelta avviene nella pagina Modelli.
  // Polling leggero per riflettere eventuali cambi fatti altrove.
  useEffect(() => {
    let cancelled = false
    async function loadActiveModel() {
      try {
        const res = await fetch('/api/models/active')
        const data = await res.json()
        if (!cancelled) setActiveModel(data?.model || null)
      } catch {
        if (!cancelled) setActiveModel(null)
      }
    }
    loadActiveModel()
    const id = setInterval(loadActiveModel, 6000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  // Verifica reale dello stato della Knowledge Base (prima veniva usata
  // la funzione docsReady come valore booleano: sempre truthy → placeholder errato).
  useEffect(() => {
    let cancelled = false
    async function checkKb() {
      try {
        const res = await fetch('/api/documents')
        const data = await res.json()
        if (!cancelled) setKbReady((data.documents || []).some(d => d.status === 'ready'))
      } catch {
        if (!cancelled) setKbReady(false)
      }
    }
    checkKb()
    const id = setInterval(checkKb, 15000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Interrogazione RAG reale via SSE
  async function handleSend() {
    const question = input.trim()
    if (!question || isStreaming) return

    setMessages(prev => [...prev, { role: 'user', content: question }])
    setInput('')
    setIsStreaming(true)
    setSources([])
    setStage('')
    setAnnounce('')
    setEmptyNotice('')

    // Reset metriche: i contatori ripartono per la nuova domanda. Il timer
    // aggiorna tok/s, token e TTFT stimati ogni 500 ms durante lo streaming.
    tokenCountRef.current = 0
    firstTokenAtRef.current = 0
    genStartRef.current = 0
    setMetrics({ tokPerSec: '—', ttft: '—', tokens: '—', retrieval: '—', live: false })
    clearInterval(metricsTimerRef.current)
    metricsTimerRef.current = setInterval(() => {
      const first = firstTokenAtRef.current
      if (!first) return
      const elapsed = (performance.now() - first) / 1000
      if (elapsed < 0.2) return
      setMetrics(m => ({
        ...m,
        tokPerSec: (tokenCountRef.current / elapsed).toFixed(1),
        tokens: String(tokenCountRef.current),
        ttft: `${((first - genStartRef.current) / 1000).toFixed(2)} s`,
        live: true,
      }))
    }, 500)

    const assistantMsg = { role: 'assistant', content: '' }
    setMessages(prev => [...prev, assistantMsg])

    try {
      const res = await fetch('/api/rag/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Nessun modello esplicito: il backend usa automaticamente
        // il modello attivo selezionato dalla pagina dedicata ai modelli.
        body: JSON.stringify({ question, retrieval_mode: retrievalMode }),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Errore ${res.status}`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))

            if (event.type === 'sources') {
              setSources(event.sources)
              if (event.sources.length > 0) setEmptyNotice('')
              setStage('')
            } else if (event.type === 'status') {
              // Fase corrente: ricerca nei documenti / generazione risposta
              setStage(event.message || '')
              if (event.empty) setEmptyNotice(event.message || '')
              // Inizio generazione: riferimento temporale per il TTFT live
              if (event.stage === 'generation') genStartRef.current = performance.now()
              // Latenza di ricerca inviata dal backend prima del primo token
              if (event.retrieval_time_ms != null) {
                setMetrics(m => ({ ...m, retrieval: `${Math.round(event.retrieval_time_ms)} ms` }))
              }
            } else if (event.type === 'token') {
              tokenCountRef.current += 1
              if (!firstTokenAtRef.current) {
                firstTokenAtRef.current = performance.now()
                // Fallback: se lo status di generazione non è arrivato,
                // il TTFT parte dal primo token (stima conservativa)
                if (!genStartRef.current) genStartRef.current = firstTokenAtRef.current
              }
              setMessages(prev => {
                const updated = [...prev]
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: updated[updated.length - 1].content + event.token,
                }
                return updated
              })
            } else if (event.type === 'metrics') {
              // Metriche autorevoli del backend: sostituiscono le stime live
              clearInterval(metricsTimerRef.current)
              setMetrics(m => ({
                ...m,
                tokPerSec: String(event.tok_per_sec),
                ttft: `${event.ttft} s`,
                tokens: String(event.tokens ?? tokenCountRef.current),
                retrieval: event.retrieval_time_ms != null
                  ? `${Math.round(event.retrieval_time_ms)} ms`
                  : m.retrieval,
                live: false,
              }))
              setAnnounce(`Risposta completata: ${tokenCountRef.current} token, `
                + `${event.tok_per_sec} token al secondo, `
                + `primo token dopo ${event.ttft} secondi.`)
            } else if (event.type === 'error') {
              clearInterval(metricsTimerRef.current)
              setAnnounce('Errore durante la generazione della risposta.')
              setMessages(prev => {
                const updated = [...prev]
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: `Errore: ${event.message}`,
                }
                return updated
              })
            }
          } catch {
            // Frammento JSON incompleto, parte della prossima iterazione
          }
        }
      }
    } catch (e) {
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `Impossibile contattare il backend: ${e.message}`,
        }
        return updated
      })
    } finally {
      setIsStreaming(false)
      setStage('')
      clearInterval(metricsTimerRef.current)
      setMetrics(m => ({ ...m, live: false }))
    }
  }

  // Pulisce l'interfaccia RAG: rimuove messaggi, fonti, metriche e resetta lo stato
  function handleClear() {
    if (isStreaming) return // Non pulire durante lo streaming
    setMessages([])
    setInput('')
    setSources([])
    setMetrics({ tokPerSec: '—', ttft: '—', tokens: '—', retrieval: '—', live: false })
    setAnnounce('')
    setStage('')
    setEmptyNotice('')
    setCopiedMetrics(false)
    setViewingDoc(null)
    // Resetta anche i contatori live
    tokenCountRef.current = 0
    firstTokenAtRef.current = 0
    genStartRef.current = 0
    clearInterval(metricsTimerRef.current)
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Copia la tabella metriche negli appunti (formato Markdown per tesi)
  async function copyMetrics() {
    const rows = [
      ['Ricerca', metrics.retrieval, 'Tempo impiegato per recuperare i documenti dalla Knowledge Base (ms)'],
      ['Throughput', `${metrics.tokPerSec} tok/s`, 'Velocità di generazione dei token al secondo'],
      ['TTFT', metrics.ttft, 'Time To First Token: tempo prima del primo token generato (ms)'],
      ['Token', `${metrics.tokens} token`, 'Numero totale di token generati nella risposta'],
    ]
    const md = '| Metrica | Valore | Descrizione |\n|---------|-------|-------------|\n' +
      rows.map(r => `| ${r[0]} | ${r[1]} | ${r[2]} |`).join('\n')
    try {
      await navigator.clipboard.writeText(md)
      setCopiedMetrics(true)
      setTimeout(() => setCopiedMetrics(false), 2000)
    } catch {
      // Fallback per browser che non supportano clipboard API
      const ta = document.createElement('textarea')
      ta.value = md
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopiedMetrics(true)
      setTimeout(() => setCopiedMetrics(false), 2000)
    }
  }

  return (
    <div className="animate-fade-in" aria-label="Interrogazione RAG">
      {/* Annuncio per screen reader a fine generazione (regione live) */}
      <span className="sr-only" role="status">{announce}</span>
      <div className="rag-header">
        <p className="rag-epistemology" role="note">
          Ogni risposta è costruita dalle evidenze disponibili
        </p>
        {/* Il modello si sceglie nella pagina dedicata (icona a rondella): qui è solo indicato */}
        <div className="rag-controls">
          <span
            className={`badge ${activeModel ? 'badge-ok' : 'badge-warn'}`}
            title={activeModel ? `Modello attivo: ${activeModel}` : 'Nessun modello attivo — selezionalo nella pagina Modelli'}
          >
            <span className="badge-dot" aria-hidden="true" />
            {activeModel || 'Nessun modello'}
          </span>
          <select
            className="rag-select"
            value={retrievalMode}
            onChange={e => setRetrievalMode(e.target.value)}
            aria-label="Modalità di retrieval"
            title="Seleziona la modalità di retrieval"
          >
            <option value="hybrid">Hybrid (Dense + BM25)</option>
            <option value="dense">Dense (Vettoriale)</option>
            <option value="bm25">BM25 (Lessicale)</option>
          </select>
          <button
            className="navbar-btn"
            onClick={() => navigate('/models')}
            aria-label="Vai alla pagina dei modelli"
            title="Gestione dei modelli"
          >
            <Settings size={16} />
          </button>
          <button
            className="navbar-btn"
            onClick={handleClear}
            disabled={isStreaming}
            aria-label="Pulisci conversazione"
            title="Rimuovi domande, risposte e fonti"
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      <div className="rag-layout">
        <div className="rag-chat" role="log" aria-label="Cronologia conversazione" aria-live="polite">
          <div className="rag-messages">
            {messages.length === 0 && (
              <div style={{ textAlign: 'center', padding: '3rem 1rem', color: 'var(--text-muted)' }}>
                <p style={{ fontSize: 'var(--text-lg)', marginBottom: '0.5rem' }}>Inserisci una domanda per interrogare la Knowledge Base</p>
                <p style={{ fontSize: 'var(--text-sm)' }}>
                  {kbReady === false
                    ? 'Carica prima dei documenti dalla KB per abilitare le interrogazioni'
                    : 'Le risposte saranno anchorate ai documenti indicizzati'}
                </p>
              </div>
            )}

            {emptyNotice && (
              <div className="rag-empty-notice" role="status">
                {emptyNotice}
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`rag-msg ${msg.role}`}>
                <div className="rag-msg-avatar" aria-hidden="true">
                  {msg.role === 'assistant' ? (
                    <img src="/jeeg.jpg" alt="Jeeg Robot" className="rag-avatar-icon" />
                  ) : (
                    <User size={18} />
                  )}
                </div>
                <div className="rag-msg-body">
                  {msg.role === 'assistant' ? (
                    <span>
                      {renderInlineMarkdown(msg.content)}
                      {isStreaming && i === messages.length - 1 && (
                        <span className="rag-typing-cursor" aria-hidden="true" />
                      )}
                      {isStreaming && i === messages.length - 1 && stage && !msg.content && (
                        <span className="rag-stage" role="status">{stage}…</span>
                      )}
                    </span>
                  ) : (
                    msg.content
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          <div className="rag-input-area">
            <label htmlFor="rag-input" className="sr-only">Inserisci la tua domanda</label>
            <textarea
              id="rag-input"
              className="rag-input"
              placeholder="Inserisci la tua domanda..."
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isStreaming}
              rows={1}
              aria-describedby="rag-input-hint"
            />
            <button
              className="rag-send-btn"
              onClick={handleSend}
              disabled={isStreaming || !input.trim()}
              aria-label="Invia domanda"
            >
              <Send size={18} />
            </button>
          </div>
          <span id="rag-input-hint" className="sr-only">Premi Invio per inviare, Shift+Invio per andare a capo</span>
        </div>

        <aside className="rag-sources" aria-label="Fonti citate">
          <div className="rag-sources-header">
            Fonti citate ({sources.length})
          </div>
          <div className="rag-sources-list" role="list">
            {sources.length === 0 ? (
              <p style={{ padding: '1rem', color: 'var(--text-muted)', fontSize: 'var(--text-sm)', textAlign: 'center' }}>
                Le fonti appariranno qui dopo la prima interrogazione
              </p>
            ) : (
              sources.map((src, i) => (
                <div key={i} className="rag-source-item" role="listitem" tabIndex={0}
                  aria-label={`Fonte ${src.ref}: ${src.document_name}`}>
                  <div className="rag-source-ref">{src.ref}</div>
                  <div className="rag-source-name">{src.document_name}</div>
                  <div className="rag-source-loc">{src.location}</div>
                  <div className="rag-source-snippet">{src.snippet}</div>
                </div>
              ))
            )}
          </div>
          <div className="rag-metrics-container">
            <div className="rag-metrics-header">
              <span className="rag-metrics-title">Metriche</span>
              <button
                className={`rag-copy-btn ${copiedMetrics ? 'copied' : ''}`}
                onClick={copyMetrics}
                title="Copia tabella per tesi (Markdown)"
              >
                {copiedMetrics ? <Check size={14} /> : <Copy size={14} />}
                {copiedMetrics ? 'Copiata!' : 'Copia'}
              </button>
            </div>
            <table className="rag-metrics-table">
              <thead>
                <tr>
                  <th>Metrica</th>
                  <th>Valore</th>
                  <th>Descrizione</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Ricerca</td>
                  <td><strong>{metrics.retrieval}</strong></td>
                  <td className="rag-metric-desc">Tempo per recuperare documenti dalla KB (ms)</td>
                </tr>
                <tr>
                  <td>Throughput</td>
                  <td><strong>{metrics.tokPerSec}</strong> tok/s</td>
                  <td className="rag-metric-desc">Velocità di generazione token al secondo</td>
                </tr>
                <tr>
                  <td>TTFT</td>
                  <td><strong>{metrics.ttft}</strong></td>
                  <td className="rag-metric-desc">Time To First Token: tempo primo token (ms)</td>
                </tr>
                <tr>
                  <td>Token</td>
                  <td><strong>{metrics.tokens}</strong></td>
                  <td className="rag-metric-desc">Numero totale di token generati</td>
                </tr>
              </tbody>
            </table>
            {metrics.live && (
              <div className="rag-metric-live">
                <span className="rag-metric-live-dot" aria-hidden="true" />
                live
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}

// Markdown inline senza dipendenze extra
function renderInlineMarkdown(text) {
  // Split by links to preserve them
  const parts = text.split(/(\[.+?\]\(.+?\))/g)
  
  return parts.map((part, i) => {
    // Check if this part is a link
    const linkMatch = part.match(/^\[(.+?)\]\((.+?)\)$/)
    if (linkMatch) {
      return <a key={i} href={linkMatch[2]} onClick={e => e.preventDefault()} className="rag-msg-citation">{linkMatch[1]}</a>
    }
    
    // For non-link parts, handle bold markers by splitting on **text**
    const boldParts = part.split(/(\*\*.+?\*\*)/g)
    return (
      <span key={i}>
        {boldParts.map((bp, j) => {
          const boldMatch = bp.match(/^\*\*(.+?)\*\*$/)
          if (boldMatch) {
            return <strong key={j}>{boldMatch[1]}</strong>
          }
          return <span key={j}>{bp}</span>
        })}
      </span>
    )
  })
}