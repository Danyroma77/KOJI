import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Send, Settings } from 'lucide-react'

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
  const [activeModel, setActiveModel] = useState(null)
  // null = verifica in corso, false = KB vuota, true = almeno un documento pronto
  const [kbReady, setKbReady] = useState(null)
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
        body: JSON.stringify({ question }),
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
              setStage('')
            } else if (event.type === 'status') {
              // Fase corrente: ricerca nei documenti / generazione risposta
              setStage(event.message || '')
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

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
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
          <button
            className="navbar-btn"
            onClick={() => navigate('/models')}
            aria-label="Vai alla pagina dei modelli"
            title="Gestione dei modelli"
          >
            <Settings size={16} />
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

            {messages.map((msg, i) => (
              <div key={i} className={`rag-msg ${msg.role}`}>
                <div className="rag-msg-avatar" aria-hidden="true">
                  {msg.role === 'assistant' ? 'KL' : 'UT'}
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
          <div className="rag-sources-footer">
            <span className="rag-metric">Ricerca <strong>{metrics.retrieval}</strong></span>
            <span className="rag-metric"><strong>{metrics.tokPerSec}</strong> tok/s</span>
            <span className="rag-metric">TTFT <strong>{metrics.ttft}</strong></span>
            <span className="rag-metric"><strong>{metrics.tokens}</strong> token</span>
            {metrics.live && (
              <span className="rag-metric-live">
                <span className="rag-metric-live-dot" aria-hidden="true" />
                live
              </span>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}

// Markdown inline senza dipendenze extra
function renderInlineMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .split(/(\[.+?\]\(.+?\))/g)
    .map((part, i) => {
      const match = part.match(/^\[(.+?)\]\((.+?)\)$/)
      if (match) {
        return <a key={i} href={match[2]} onClick={e => e.preventDefault()} className="rag-msg-citation">{match[1]}</a>
      }
      return <span key={i}>{part}</span>
    })
}