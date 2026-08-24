import { useState, useEffect } from 'react'

const FIELDS = [
  { key: 'chunk_size', label: 'Dimensione chunk (token)', desc: 'Numero di token per ciascun segmento. Default: 512', min: 64, max: 2048, step: 64, type: 'number' },
  { key: 'chunk_overlap_pct', label: 'Overlap chunk (%)', desc: 'Percentuale di sovrapposizione tra chunk. Default: 20', min: 0, max: 50, step: 5, type: 'number' },
  { key: 'embedding_model', label: 'Modello di embedding', desc: 'Modello sentence-transformer. Richiede rebuild della KB.', type: 'text' },
  { hnsw_m: 'hnsw_m', label: 'Parametro M (HNSW)', desc: 'Connessioni massime per nodo. Maggiore = piu preciso ma piu lento. Default: 16', min: 4, max: 64, step: 1, type: 'number' },
  { key: 'hnsw_ef_construction', label: 'ef_construction (HNSW)', desc: 'Candidate list durante costruzione. Default: 200', min: 50, max: 500, step: 10, type: 'number' },
  { graph_confidence_threshold: 'graph_confidence_threshold', label: 'Soglia confidence (Grafo)', desc: 'Soglia minima per includere una relazione. Default: 0.7', min: 0, max: 1, step: 0.05, type: 'number' },
  { key: 'metrics_interval_sec', label: 'Intervallo polling (secondi)', desc: 'Frequenza aggiornamento metriche dashboard. Default: 5', min: 1, max: 60, step: 1, type: 'number' },
]

export default function Admin() {
  const [config, setConfig] = useState({})
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/admin/config')
      .then(r => r.json())
      .then(setConfig)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  function handleChange(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }))
    setSaved(false)
  }

  async function handleSave() {
    const payload = {}
    FIELDS.forEach(f => {
      if (config[f.key] !== undefined && config[f.key] !== null) {
        payload[f.key] = f.type === 'number' ? Number(config[f.key]) : config[f.key]
      }
    })
    try {
      fetch('/api/admin/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(res => {
        if (res.ok) {
          setSaved(true)
          setTimeout(() => setSaved(false), 2000)
        }
      })
    } catch (e) {
      alert('Errore nel salvataggio: ' + e.message)
    }
  }

  if (loading) {
    return (
      <div className="animate-fade-in" aria-label="Amministrazione">
        <div className="admin-header"><h2>Amministrazione</h2></div>
        <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-muted)' }}>Caricamento configurazione...</div>
      </div>
    )
  }

  return (
    <div className="animate-fade-in" aria-label="Amministrazione">
      <div className="admin-header"><h2>Amministrazione</h2></div>

      <div className="admin-section animate-slide-up stagger-1">
        <h3>Elaborazione documenti</h3>
        {FIELDS.slice(0, 2).map(f => (
          <div key={f.key} className="admin-field">
            <label className="admin-field-label" htmlFor={f.key}>{f.label}</label>
            <p className="admin-field-desc">{f.desc}</p>
            <input id={f.key} type={f.type} className="admin-input"
              value={config[f.key] ?? ''} onChange={e => handleChange(f.key, e.target.value)}
              min={f.min} max={f.max} step={f.step} />
          </div>
        ))}
      </div>

      <div className="admin-section animate-slide-up stagger-2">
        <h3>Indice vettoriale (HNSW)</h3>
        {FIELDS.slice(2, 4).map(f => (
          <div key={f.key} className="admin-field">
            <label className="admin-field-label" htmlFor={f.key}>{f.label}</label>
            <p className="admin-field-desc">{f.desc}</p>
            <input id={f.key} type="number" className="admin-input"
              value={config[f.key] ?? ''} onChange={e => handleChange(f.key, e.target.value)}
              min={f.min} max={f.max} step={f.step} />
          </div>
        ))}
      </div>

      <div className="admin-section animate-slide-up stagger-3">
        <h3>Knowledge Graph</h3>
        {FIELDS.slice(4, 6).map(f => (
          <div key={f.key} className="admin-field">
            <label className="admin-field-label" htmlFor={f.key}>{f.label}</label>
            <p className="admin-field-desc">{f.desc}</p>
            <input id={f.key} type="number" className="admin-input"
              value={config[f.key] ?? ''} onChange={e => handleChange(f.key, e.target.value)}
              min={f.min} max={f.max} step={f.step} />
          </div>
        ))}
      </div>

      <div className="admin-section animate-slide-up stagger-4">
        <h3>Monitoraggio</h3>
        {FIELDS.slice(6, 7).map(f => (
          <div key={f.key} className="admin-field">
            <label className="admin-field-label" htmlFor={f.key}>{f.label}</label>
            <p className="admin-field-desc">{f.desc}</p>
            <input id={f.key} type="number" className="admin-input"
              value={config[f.key] ?? ''} onChange={e => handleChange(f.key, e.target.value)}
              min={f.min} max={f.max} step={f.step} />
          </div>
        ))}
      </div>

      <div className="admin-input-row animate-slide-up stagger-5" style={{ marginTop: 'var(--space-lg)' }}>
        <button className="admin-btn admin-btn-primary" onClick={handleSave}>
          {saved ? '✓ Salvato' : 'Salva configurazione'}
        </button>
      </div>
    </div>
  )
}