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

  useEffect(() => {
    let interval
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
    fetchMetrics()
    fetchServices()
    interval = setInterval(() => { fetchMetrics(); fetchServices() }, 3000)
    return () => clearInterval(interval)
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
          <h3><Gauge size={14} /> Prestazioni LLM</h3>
          <Bar value={10} max={20} label="Throughput" valueLabel={`${m.active_model}`} />
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