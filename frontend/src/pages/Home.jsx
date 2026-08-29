import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Upload, MessageSquare, Network, Database, Cpu, FileText, Clock } from 'lucide-react'
import { listActivities } from '../services/documents'

const SERVICE_MAP = {
  'LLM Runtime': 'ollama',
  'Vector DB': 'chromadb',
  'File Store': 'file_store',
  'API Layer': 'api',
}

// Etichette in italiano per la tipologia di modifica mostrata nella tabella attività
const ACTIVITY_TYPE_MAP = {
  uploaded: { label: 'Caricato', cls: 'badge-info' },
  modified: { label: 'Modificato', cls: 'badge-warn' },
  deleted: { label: 'Eliminato', cls: 'badge-error' },
  parsing: { label: 'Analisi', cls: 'badge-warn' },
  normalizing: { label: 'Normalizzazione', cls: 'badge-warn' },
  chunking: { label: 'Suddivisione in chunk', cls: 'badge-warn' },
  embedding: { label: 'Vettorizzazione', cls: 'badge-warn' },
  ready: { label: 'Indicizzato', cls: 'badge-ok' },
  error: { label: 'Errore', cls: 'badge-error' },
  reprocessing: { label: 'Riprocessato', cls: 'badge-info' },
  wiki_generated: { label: 'Wiki generata', cls: 'badge-info' },
  graph_extracted: { label: 'Grafo estratto', cls: 'badge-info' },
}

export default function Home() {
  const navigate = useNavigate()

  // Stato reale
  const [metrics, setMetrics] = useState(null)
  const [docs, setDocs] = useState([])
  const [activities, setActivities] = useState([])
  const [serviceStates, setServiceStates] = useState(
    () => Object.fromEntries(Object.keys(SERVICE_MAP).map(s => [s, 'checking']))
  )

  // --- Servizi ---
  const checkServices = useCallback(async () => {
    try {
      const res = await fetch('/api/system/status')
      if (!res.ok) throw new Error()
      const data = await res.json()
      const next = {}
      for (const [label, key] of Object.entries(SERVICE_MAP)) {
        next[label] = data[key] ? 'ok' : 'fail'
      }
      next['API Layer'] = 'ok'
      setServiceStates(next)
    } catch {
      setServiceStates(
        Object.fromEntries(Object.keys(SERVICE_MAP).map(s => [s, 'fail']))
      )
    }
  }, [])

  // --- Metriche + documenti + cronologia attività ---
  // Ogni risorsa viene gestita in un blocco indipendente: un errore su
  // metriche o documenti non deve MAI impedire il caricamento della
  // cronologia attività (che altrimenti resterebbe vuota sulla home).
  const fetchData = useCallback(async () => {
    const [metricsRes, docsRes] = await Promise.all([
      fetch('/api/system/metrics').catch(() => null),
      fetch('/api/documents').catch(() => null),
    ])

    if (metricsRes && metricsRes.ok) {
      try {
        setMetrics(await metricsRes.json())
      } catch {
        // Risposta non parsabile: si riprova al prossimo tick
      }
    }

    if (docsRes && docsRes.ok) {
      try {
        const data = await docsRes.json()
        setDocs(data.documents || [])
      } catch {
        // Risposta non parsabile: si riprova al prossimo tick
      }
    }

    // Cronologia attività dal log persistente: oltre a upload e indicizzazione
    // include le modifiche (sovrascrittura di un file) e le eliminazioni,
    // che altrimenti sparirebbero insieme al documento dal catalogo.
    // Limitata agli ultimi 15 eventi.
    try {
      const data = await listActivities(15)
      const recent = (data.activities || []).map(a => {
        const dateTime = a.timestamp
          ? new Date(a.timestamp).toLocaleString('it-IT', {
              day: '2-digit', month: '2-digit', year: 'numeric',
              hour: '2-digit', minute: '2-digit',
            })
          : '—'
        const type = ACTIVITY_TYPE_MAP[a.action] || { label: a.action || 'Sconosciuto', cls: 'badge-info' }
        return {
          id: a.id,
          dateTime,
          filename: a.filename,
          type,
          detail: a.detail || '',
          status: a.action,
        }
      })
      setActivities(recent)
    } catch {
      // Silenzioso — al prossimo tick riprova
    }
  }, [])

  // --- Avvio + polling ---
  useEffect(() => {
    checkServices()
    fetchData()

    // Servizi ogni 15s, dati ogni 5s
    const serviceInterval = setInterval(checkServices, 15000)
    const dataInterval = setInterval(fetchData, 5000)

    return () => {
      clearInterval(serviceInterval)
      clearInterval(dataInterval)
    }
  }, [checkServices, fetchData])

  // --- Derivati ---
  const totalDocs = docs.length
  const totalChunks = docs.reduce((s, d) => s + (d.chunks_count || 0), 0)
  const processingCount = docs.filter(d => !['ready', 'error'].includes(d.status)).length
  const ramDisplay = metrics
    ? `${metrics.ram_used_gb.toFixed(1)} / ${metrics.ram_total_gb.toFixed(1)} GB`
    : '— / — GB'
  const cpuDisplay = metrics ? `${metrics.cpu_percent.toFixed(0)}%` : '—%'
  const tokDisplay = metrics ? (metrics.active_model || '—') : '—'

  // Tutti i servizi ok?
  const allOk = Object.values(serviceStates).every(s => s === 'ok')
  const someFail = Object.values(serviceStates).some(s => s === 'fail')

  return (
    <div className="animate-fade-in">
      <a href="#main-content" className="skip-link">Vai al contenuto principale</a>

      {/* Benvenuto */}
      <section className="home-welcome" aria-label="Benvenuto">
        <h1>
          Benvenuto <span className="accent">comandante</span>,
          {allOk
            ? ' tutti i sistemi sono operativi e pronti'
            : someFail
              ? ' alcuni sistemi richiedono attenzione'
              : ' inizializzazione sistemi in corso...'
          }
        </h1>
        <p className="home-subtitle">
          Piattaforma locale di gestione della conoscenza — nessun dato lascia questo dispositivo.
        </p>

        <div className="home-service-check" role="list" aria-label="Stato dei servizi">
          {Object.entries(serviceStates).map(([name, state]) => (
            <div
              key={name}
              className={`service-check-item ${state}`}
              role="listitem"
              aria-label={`${name}: ${state === 'ok' ? 'operativo' : state === 'fail' ? 'non disponibile' : 'verifica in corso'}`}
            >
              {state === 'ok' && '✓'}
              {state === 'fail' && '✗'}
              {state === 'checking' && '◐'}
              {' '}{name}
            </div>
          ))}
        </div>
      </section>

      {/* Card stato — dati reali */}
      <div className="home-grid-top" aria-label="Sintesi dello stato">
        <div className="card animate-slide-up stagger-1">
          <div className="card-header">
            <span className="card-title">
              <Database size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
              Stato KB
            </span>
          </div>
          <div className="card-value">{totalDocs}</div>
          <div className="card-sub">
            documenti indicizzati
            {processingCount > 0 && (
              <span style={{ color: 'var(--jeeg-amber)', marginLeft: 6 }}>
                · {processingCount} in elaborazione
              </span>
            )}
          </div>
        </div>

        <div className="card animate-slide-up stagger-2">
          <div className="card-header">
            <span className="card-title">
              <FileText size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
              Chunk
            </span>
          </div>
          <div className="card-value">{totalChunks.toLocaleString()}</div>
          <div className="card-sub">
            segmenti indicizzati in ChromaDB
          </div>
        </div>

        <div className="card animate-slide-up stagger-3">
          <div className="card-header">
            <span className="card-title">
              <Cpu size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
              Sistema
            </span>
          </div>
          <div className="card-value" style={{ fontSize: 'var(--text-xl)' }}>{ramDisplay}</div>
          <div className="card-sub">CPU {cpuDisplay} · {tokDisplay}</div>
        </div>
      </div>

      {/* Attività + Azioni rapide */}
      <div className="home-grid-bottom" aria-label="Attività e azioni">
        <div className="card animate-slide-up stagger-4">
          <div className="card-header">
            <span className="card-title">
              <Clock size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
              Attività recenti
            </span>
          </div>
          {activities.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', padding: '1rem 0' }}>
              Nessuna attività — carica i primi documenti dalla KB.
            </p>
          ) : (
            <div className="home-activity-table-wrap">
              <table className="kb-table home-activity-table" aria-label="Cronologia attività">
                <thead>
                  <tr>
                    <th scope="col" style={{ width: '160px' }}>Data e ora</th>
                    <th scope="col">File</th>
                    <th scope="col" style={{ width: '180px' }}>Tipologia di modifica</th>
                  </tr>
                </thead>
                <tbody>
                  {activities.map(a => (
                    <tr key={a.id || a.dateTime + a.filename} className={a.status === 'error' ? 'row-error' : ''}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)', whiteSpace: 'nowrap' }}>
                        {a.dateTime}
                      </td>
                      <td className="doc-name" title={a.detail || a.filename}>
                        {a.filename}
                        {a.detail && (
                          <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}> · {a.detail}</span>
                        )}
                      </td>
                      <td>
                        <span className={`badge ${a.type.cls}`}>
                          <span className="badge-dot" aria-hidden="true" />
                          {a.type.label}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="card animate-slide-up stagger-5">
          <div className="card-header">
            <span className="card-title">Azioni rapide</span>
          </div>
          <div className="quick-actions">
            <button className="quick-action-btn" onClick={() => navigate('/kb')}>
              <Upload /> Carica documenti
            </button>
            <button className="quick-action-btn" onClick={() => navigate('/rag')}>
              <MessageSquare /> Interroga la KB
            </button>
            <button className="quick-action-btn" onClick={() => navigate('/graph')}>
              <Network /> Esplora il grafo
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}