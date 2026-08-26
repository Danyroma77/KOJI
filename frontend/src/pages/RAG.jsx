import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Send, Settings } from 'lucide-react'

export default function RAG() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [sources, setSources] = useState([])
  const [metrics, setMetrics] = useState({ tokPerSec: '—', ttft: '—' })
  const [activeModel, setActiveModel] = useState(null)
  const messagesEndRef = useRef(null)
  const navigate = useNavigate()

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
            } else if (event.type === 'token') {
              setMessages(prev => {
                const updated = [...prev]
                updated[updated.length - 1] = {
                  ...updated[updated.length - 1],
                  content: updated[updated.length - 1].content + event.token,
                }
                return updated
              })
            } else if (event.type === 'metrics') {
              setMetrics({
                tokPerSec: String(event.tok_per_sec),
                ttft: String(event.ttft),
              })
            } else if (event.type === 'error') {
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
                  {docsReady
                    ? 'Le risposte saranno anchorate ai documenti indicizzati'
                    : 'Carica prima dei documenti dalla KB per abilitare le interrogazioni'}
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
            <span>{metrics.tokPerSec} tok/s</span>
            <span>TTFT {metrics.ttft}</span>
          </div>
        </aside>
      </div>
    </div>
  )
}

// Verifica se ci sono documenti pronti (per il messaggio placeholder)
let _docsReady = null
async function docsReady() {
  if (_docsReady !== null) return _docsReady
  try {
    const res = await fetch('/api/documents')
    const data = await res.json()
    _docsReady = data.documents.some(d => d.status === 'ready')
  } catch {
    _docsReady = false
  }
  return _docsReady
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