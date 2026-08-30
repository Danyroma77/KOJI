import { useState, useEffect, useMemo, useCallback } from 'react'
import { Cpu, MemoryStick, Gauge, Server, History, RefreshCw, ChevronLeft, ChevronRight } from 'lucide-react'
import { listActivities } from '../services/documents'

// Etichette condivise con la home per la tipologia di attività
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
}

function Bar({ value, max = 100, label, valueLabel, warnAt = 70, critAt = 90 }) {
  const pct = Math.min(100, (value / max) * 100)
  const cls = pct >= critAt ? 'critical' : pct >= warnAt ? 'warn' : ''
  return (
    <div className="monitor-metric">
      <div className="monitor-metric-label">
        <span>{label}</span>
        <span className="monitor-metric-value">{valueLabel || value}</span>
      </div>
      <div className="monitor-bar-track" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max} aria-label={label}>
        <div className={`monitor-bar-fill ${cls}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// --- Storico attività -------------------------------------------------------
// Dimensioni di fetching e paginazione della card.
// FETCH_LIMIT_NEW: cap dell'endpoint aggiornato (= MAX_ACTIVITIES del log).
// FETCH_LIMIT_OLD: immagine API precedente, validazione limit<=50.
const PAGE_SIZE = 15
const FETCH_LIMIT_NEW = 200
const FETCH_LIMIT_OLD = 50

// Memoizzato a livello di modulo: una volta individuato il limite accettato
// dall'API si evita di ripetere il fallback 422 → 50 a ogni refresh.
let activityFetchLimit = null

function formatDateTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('it-IT', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function mapEntry(a) {
  const type = ACTIVITY_TYPE_MAP[a.action]
    || { label: a.action || 'Sconosciuto', cls: 'badge-info' }
  return {
    id: a.id,
    action: a.action,
    label: type.label,
    cls: type.cls,
    dateTime: formatDateTime(a.timestamp),
    filename: a.filename || 'documento',
    detail: a.detail || '',
  }
}

function totalOf(data) {
  const count = Array.isArray(data.activities) ? data.activities.length : 0
  return typeof data.total === 'number' && data.total > 0 ? data.total : count
}

/**
 * Box "Storico attività": tutte le voci del registro paginate a 15 eventi con
 * tasti Precedenti/Successivi, filtro testuale su documento/dettaglio e
 * selezione della tipologia. Refresh leggero ogni 10 s che preserva filtri
 * e pagina corrente.
 */
function ActivityHistory() {
  const [entries, setEntries] = useState([])
  const [total, setTotal] = useState(0)
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(false)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [page, setPage] = useState(0)

  const load = useCallback(async () => {
    try {
      // Storico completo (fino a 200 eventi) con backend aggiornato
      const data = await listActivities(activityFetchLimit || FETCH_LIMIT_NEW)
      activityFetchLimit = activityFetchLimit || FETCH_LIMIT_NEW
      setEntries((data.activities || []).map(mapEntry))
      setTotal(totalOf(data))
      setFailed(false)
    } catch {
      // Immagine API non ancora ricostruita: l'endpoint valida limit<=50 e
      // risponde 422 su limit=200 — si ripiega sui 50 eventi più recenti
      // senza rompere il box.
      try {
        const data = await listActivities(FETCH_LIMIT_OLD)
        activityFetchLimit = FETCH_LIMIT_OLD
        setEntries((data.activities || []).map(mapEntry))
        setTotal(totalOf(data))
        setFailed(false)
      } catch {
        setFailed(true)
      }
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    load()
    const iv = setInterval(load, 10000)
    return () => clearInterval(iv)
  }, [load])

  // Conteggio voci per tipologia: alimenta le opzioni della select
  const counts = useMemo(() => {
    const acc = {}
    for (const e of entries) acc[e.action] = (acc[e.action] || 0) + 1
    return acc
  }, [entries])

  // Filtri applicati lato client sull'intero set scaricato
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q && typeFilter === 'all') return entries
    return entries.filter(e =>
      (typeFilter === 'all' || e.action === typeFilter) &&
      (!q ||
        e.filename.toLowerCase().includes(q) ||
        e.detail.toLowerCase().includes(q))
    )
  }, [entries, search, typeFilter])

  // La pagina resta sempre valida anche se i filtri riducono l'elenco
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount - 1)
  const rows = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE)

  // Un cambio di filtri riporta all'inizio dell'elenco
  function updateSearch(value) {
    setSearch(value)
    setPage(0)
  }

  function updateType(value) {
    setTypeFilter(value)
    setPage(0)
  }

  const showLegacyNote = loaded && activityFetchLimit === FETCH_LIMIT_OLD

  return (
    <div className="monitor-card activity-card animate-slide-up">
      <h3><History size={14} /> Storico attività</h3>

      <div className="activity-toolbar">
        <input
          className="rag-input activity-search"
          type="search"
          placeholder="Filtra per documento o dettaglio…"
          value={search}
          onChange={e => updateSearch(e.target.value)}
          aria-label="Filtro testo sulle attività"
        />
        <select
          className="rag-select"
          value={typeFilter}
          onChange={e => updateType(e.target.value)}
          aria-label="Filtro per tipologia di attività"
        >
          <option value="all">Tutte le tipologie ({entries.length})</option>
          {Object.keys(ACTIVITY_TYPE_MAP)
            .filter(key => counts[key])
            .map(key => (
              <option key={key} value={key}>
                {ACTIVITY_TYPE_MAP[key].label} ({counts[key]})
              </option>
            ))}
        </select>
        <button className="activity-btn" onClick={load} title="Aggiorna lo storico ora">
          <RefreshCw size={13} /> Aggiorna
        </button>
      </div>

      {!loaded ? (
        <p className="activity-empty">Caricamento attività…</p>
      ) : failed && entries.length === 0 ? (
        <p className="activity-empty">Storico attività non disponibile.</p>
      ) : filtered.length === 0 ? (
        <p className="activity-empty">Nessuna attività corrisponde ai filtri.</p>
      ) : (
        <div className="activity-table-wrap">
          <table className="kb-table activity-table">
            <thead>
              <tr>
                <th>Quando</th>
                <th>Attività</th>
                <th>Documento</th>
                <th>Dettaglio</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(a => (
                <tr
                  key={a.id || `${a.dateTime}-${a.filename}-${a.action}`}
                  className={a.action === 'error' ? 'row-error' : ''}
                >
                  <td className="activity-when">{a.dateTime}</td>
                  <td>
                    <span className={`badge ${a.cls}`}>
                      <span className="badge-dot" aria-hidden="true" />
                      {a.label}
                    </span>
                  </td>
                  <td className="doc-name">{a.filename}</td>
                  <td className="activity-detail">{a.detail || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {loaded && filtered.length > 0 && (
        <div className="activity-pager">
          <span className="activity-pager-info">
            Pagina {safePage + 1} di {pageCount} · {filtered.length} eventi
            {total > filtered.length ? ` su ${total} registrati` : ''}
            {showLegacyNote ? " · mostrati gli ultimi 50 (ricostruisci l'immagine API per lo storico completo)" : ''}
          </span>
          <div className="activity-pager-btns">
            <button
              className="activity-btn"
              disabled={safePage === 0}
              onClick={() => setPage(safePage - 1)}
              aria-label="Pagina precedente"
            >
              <ChevronLeft size={14} /> Precedenti
            </button>
            <button
              className="activity-btn"
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage(safePage + 1)}
              aria-label="Pagina successiva"
            >
              Successivi <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function Monitor() {
  const [m, setM] = useState(null)
  const [services, setServices] = useState(null)
  // Stato dei modelli LLM dalla stessa fonte della pagina Modelli (/api/models/catalog)
  const [modelStatus, setModelStatus] = useState(null)
  const [modelsLoaded, setModelsLoaded] = useState(false)

  useEffect(() => {
    let interval
    let modelsInterval
    async function fetchMetrics() {
      try {
        const res = await fetch('/api/system/metrics')
        if (res.ok) setM(await res.json())
      } catch {}
    }
    async function fetchServices() {
      try {
        const res = await fetch('/api/system/status')
        if (res.ok) setServices(await res.json())
      } catch {}
    }
    // Stato del modello attivo: scaricato, in linea (caricato in memoria), keep-alive
    async function fetchModelStatus() {
      try {
        const res = await fetch('/api/models/catalog')
        if (!res.ok) throw new Error()
        const data = await res.json()
        const models = Array.isArray(data.models) ? data.models : []
        const active = models.find(mo => mo.active) || null
        setModelStatus({
          reachable: data.reachable ?? false,
          activeModel: data.active_model || null,
          activeLabel: active?.label || null,
          online: Boolean(active?.online),
          downloaded: Boolean(active?.downloaded),
          keepAlive: data.keep_alive || null,
        })
      } catch {
        setModelStatus(null)
      } finally {
        setModelsLoaded(true)
      }
    }
    fetchMetrics()
    fetchServices()
    fetchModelStatus()
    interval = setInterval(() => { fetchMetrics(); fetchServices() }, 3000)
    modelsInterval = setInterval(fetchModelStatus, 6000)
    return () => { clearInterval(interval); clearInterval(modelsInterval) }
  }, [])

  if (!m) {
    return (
      <div className="animate-fade-in" aria-label="Monitoraggio sistema">
        <div className="monitor-header"><h2>Monitoraggio sistema</h2></div>
        <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>Caricamento metriche...</div>
      </div>
    )
  }

  return (
    <div className="animate-fade-in" aria-label="Monitoraggio sistema">
      <div className="monitor-header"><h2>Monitoraggio sistema</h2></div>
      <div className="monitor-grid">
        <div className="monitor-card animate-slide-up stagger-1">
          <h3><Cpu size={14} /> Risorse hardware</h3>
          <Bar value={m.cpu_percent} max={100} label="CPU" valueLabel={`${m.cpu_percent.toFixed(1)}%`} warnAt={70} critAt={90} />
          <Bar value={m.ram_used_gb} max={m.ram_total_gb} label="RAM" valueLabel={`${m.ram_used_gb.toFixed(1)} / ${m.ram_total_gb.toFixed(1)} GB`} warnAt={70} critAt={90} />
          {m.vram_total_mb ? (
            <Bar value={m.vram_used_mb || 0} max={m.vram_total_mb} label="VRAM (dedicata)" valueLabel={`${(m.vram_used_mb || 0).toFixed(0)} / ${m.vram_total_mb.toFixed(0)} MB`} />
          ) : (
            <Bar value={0} max={1} label="VRAM (dedicata)" valueLabel="Non disponibile" />
          )}
        </div>
        <div className="monitor-card animate-slide-up stagger-2">
          <h3><Gauge size={14} /> Modello LLM</h3>
          {!modelsLoaded ? null : !modelStatus ? (
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>
              Stato modelli non disponibile
            </p>
          ) : (
            <>
              <div className="monitor-service-item">
                <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ color: modelStatus.reachable
                    ? (modelStatus.online ? 'var(--jeeg-green)' : 'var(--jeeg-blue)')
                    : 'var(--jeeg-red)' }}>●</span>
                  Modello attivo
                </span>
                {modelStatus.reachable ? (
                  <span className={`badge ${modelStatus.online ? 'badge-ok' : modelStatus.downloaded ? 'badge-info' : 'badge-warn'}`}>
                    <span className="badge-dot" aria-hidden="true" />
                    {modelStatus.online ? 'In linea' : modelStatus.downloaded ? 'Pronto' : 'Non scaricato'}
                  </span>
                ) : (
                  <span className="badge badge-error"><span className="badge-dot" aria-hidden="true" />Ollama offline</span>
                )}
              </div>
              <div className="monitor-service-item">
                <span style={{ color: 'var(--text-muted)' }}>Nome</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }} title={modelStatus.activeLabel || modelStatus.activeModel || ''}>
                  {modelStatus.activeLabel || modelStatus.activeModel || '—'}
                </span>
              </div>
              {modelStatus.keepAlive && (
                <div className="monitor-service-item">
                  <span style={{ color: 'var(--text-muted)' }}>Keep alive</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
                    {modelStatus.keepAlive}
                  </span>
                </div>
              )}
            </>
          )}
        </div>
        <div className="monitor-card animate-slide-up stagger-3">
          <h3><MemoryStick size={14} /> Stato Retrieval</h3>
          <Bar value={m.total_chunks || 0} max={5000} label="Chunk indicizzati" valueLabel={`${m.total_chunks?.toLocaleString() || 0}`} />
        </div>
        <div className="monitor-card animate-slide-up stagger-4">
          <h3><Server size={14} /> Stato servizi</h3>
          {services && (
            <>
              <div className="monitor-service-item"><span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className={services.ollama ? '' : '❌'} style={{ color: services.ollama ? 'var(--green-text)' : 'var(--red-text)' }}>●</span>
                Ollama (LLM Runtime)
              </span><span className={`badge ${services.ollama ? 'badge-ok' : 'badge-error'}`}><span className="badge-dot" aria-hidden="true" />{services.ollama ? 'Online' : 'Offline'}</span></div>
              <div className="monitor-service-item"><span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className={services.chromadb ? '' : '❌'} style={{ color: services.chromadb ? 'var(--green-text)' : 'var(--red-text)' }}>●</span>
                ChromaDB (Vector Store)
              </span><span className={`badge ${services.chromadb ? 'badge-ok' : 'badge-error'}`}><span className="badge-dot" aria-hidden="true" />{services.chromadb ? 'Online' : 'Offline'}</span></div>
              <div className="monitor-service-item"><span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className={services.file_store ? '' : '❌'} style={{ color: services.file_store ? 'var(--green-text)' : 'var(--red-text)' }}>●</span>
                File Store
              </span><span className={`badge ${services.file_store ? 'badge-ok' : 'badge-error'}`}><span className="badge-dot" aria-hidden="true" />{services.file_store ? 'Online' : 'Offline'}</span></div>
              <div className="monitor-service-item"><span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: 'var(--green-text)' }}>●</span>
                API Layer (FastAPI)
              </span><span className="badge badge-ok"><span className="badge-dot" aria-hidden="true" />Online</span></div>
            </>
          )}
        </div>
      </div>
      <ActivityHistory />
    </div>
  )
}