import { useState, useEffect } from 'react'
import { Cpu, MemoryStick, Gauge, Server } from 'lucide-react'

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
          onlineCount: models.filter(mo => mo.online).length,
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
              <div className="monitor-service-item">
                <span style={{ color: 'var(--text-muted)' }}>Modelli in linea</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-xs)' }}>
                  {modelStatus.onlineCount}
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
                <span className={services.ollama ? '' : '❌'} style={{ color: services.ollama ? 'var(--jeeg-green)' : 'var(--jeeg-red)' }}>●</span>
                Ollama (LLM Runtime)
              </span><span className={`badge ${services.ollama ? 'badge-ok' : 'badge-error'}`}><span className="badge-dot" aria-hidden="true" />{services.ollama ? 'Online' : 'Offline'}</span></div>
              <div className="monitor-service-item"><span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className={services.chromadb ? '' : '❌'} style={{ color: services.chromadb ? 'var(--jeeg-green)' : 'var(--jeeg-red)' }}>●</span>
                ChromaDB (Vector Store)
              </span><span className={`badge ${services.chromadb ? 'badge-ok' : 'badge-error'}`}><span className="badge-dot" aria-hidden="true" />{services.chromadb ? 'Online' : 'Offline'}</span></div>
              <div className="monitor-service-item"><span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className={services.file_store ? '' : '❌'} style={{ color: services.file_store ? 'var(--jeeg-green)' : 'var(--jeeg-red)' }}>●</span>
                File Store
              </span><span className={`badge ${services.file_store ? 'badge-ok' : 'badge-error'}`}><span className="badge-dot" aria-hidden="true" />{services.file_store ? 'Online' : 'Offline'}</span></div>
              <div className="monitor-service-item"><span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ color: 'var(--jeeg-green)' }}>●</span>
                API Layer (FastAPI)
              </span><span className="badge badge-ok"><span className="badge-dot" aria-hidden="true" />Online</span></div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}