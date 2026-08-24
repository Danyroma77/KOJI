import { useState, useEffect } from 'react'

const BOOT_STEPS = [
  { text: 'Loading Memory', delay: 0 },
  { text: 'Loading Brain', delay: 900 },
  { text: 'Loading Knowledge System', delay: 1800 },
  { text: 'Starting AI Runtime', delay: 2700 },
]

const POLL_MS = 6000

export default function Models() {
  const [bootLines, setBootLines] = useState(BOOT_STEPS.map(() => ({ text: '', status: 'pending' })))
  const [bootDone, setBootDone] = useState(false)

  // Catalogo dei modelli messi a disposizione + stato reale rispetto a Ollama
  const [catalog, setCatalog] = useState([])
  const [reachable, setReachable] = useState(null)
  const [activeModel, setActiveModel] = useState(null)
  const [keepAlive, setKeepAlive] = useState(null)
  const [busy, setBusy] = useState({})
  const [progress, setProgress] = useState({})
  const [actionError, setActionError] = useState(null)

  // Sequenza boot animata
  useEffect(() => {
    const timers = []
    BOOT_STEPS.forEach((step, i) => {
      timers.push(setTimeout(() => {
        setBootLines(prev => {
          const updated = [...prev]
          updated[i] = { text: step.text, status: 'loading' }
          return updated
        })
      }, step.delay))
      timers.push(setTimeout(() => {
        setBootLines(prev => {
          const updated = [...prev]
          updated[i] = { text: step.text, status: 'ok' }
          return updated
        })
      }, step.delay + 600))
    })
    timers.push(setTimeout(() => setBootDone(true), BOOT_STEPS[BOOT_STEPS.length - 1].delay + 1000))
    return () => timers.forEach(clearTimeout)
  }, [])

  async function refreshCatalog() {
    try {
      const res = await fetch('/api/models/catalog')
      if (!res.ok) throw new Error()
      const data = await res.json()
      setReachable(data.reachable ?? false)
      setActiveModel(data.active_model || null)
      setKeepAlive(data.keep_alive || null)
      setCatalog(Array.isArray(data.models) ? data.models : [])
    } catch {
      setReachable(false)
      setCatalog([])
    }
  }

  // Carica il catalogo dopo l'avvio e mantiene lo stato sincronizzato
  useEffect(() => {
    if (!bootDone) return
    refreshCatalog()
    const id = setInterval(refreshCatalog, POLL_MS)
    return () => clearInterval(id)
  }, [bootDone])

  const setBusyFlag = (key, value) => setBusy(prev => ({ ...prev, [key]: value }))

  async function pollPullProgress(model) {
    for (let i = 0; i < 2400; i++) {
      await new Promise(r => setTimeout(r, 1500))
      let state = null
      try {
        const res = await fetch(`/api/models/pull/progress?model=${encodeURIComponent(model)}`)
        if (res.ok) state = await res.json()
      } catch {
        continue
      }
      if (!state) continue
      setProgress(prev => ({ ...prev, [model]: state }))
      if (state.status === 'success' || state.status === 'idle') return
      if (state.status === 'error') throw new Error(state.message || 'Errore durante il download')
    }
  }

  async function handlePull(model) {
    setBusyFlag(`pull:${model}`, true)
    setActionError(null)
    try {
      const res = await fetch('/api/models/pull', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }),
      })
      if (!res.ok) throw new Error(`Errore durante il download (HTTP ${res.status})`)
      await pollPullProgress(model)
    } catch (e) {
      setActionError(e.message || 'Errore durante il download')
    } finally {
      setBusyFlag(`pull:${model}`, false)
      refreshCatalog()
    }
  }

  async function postAction(url, payload, busyKey, errMsg) {
    setBusyFlag(busyKey, true)
    setActionError(null)
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`${errMsg} (HTTP ${res.status})`)
    } catch (e) {
      setActionError(e.message || errMsg)
    } finally {
      setBusyFlag(busyKey, false)
      refreshCatalog()
    }
  }

  const handleLoad = (model) => postAction('/api/models/load', { model, keep_alive: keepAlive }, `load:${model}`, 'Impossibile caricare il modello')
  const handleUnload = (model) => postAction('/api/models/unload', { model }, `unload:${model}`, 'Impossibile scaricare il modello')
  const handleSelect = (model) => {
    postAction('/api/models/select', { model }, `select:${model}`, 'Errore durante la selezione')
  }

  function formatSize(bytes) {
    if (!bytes) return null
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
    if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`
    if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`
    return `${bytes} B`
  }

  return (
    <div className="models-page animate-fade-in" aria-label="Gestione modelli">
      <div className="boot-container">
        <div className="boot-terminal" role="log" aria-label="Sequenza di avvio" aria-live="polite">
          {bootLines.map((line, i) => (
            <div key={i} className={`boot-line ${line.status !== 'pending' ? 'visible' : ''}`}>
              <span className="boot-line-text">{line.text}</span>
              {line.status === 'loading' && (
                <span className="boot-line-dots" aria-hidden="true" style={{ animation: 'blink-green 0.5s step-end infinite' }}>....</span>
              )}
              <span className={`boot-line-status ${line.status}`} aria-label={line.status === 'ok' ? 'OK' : line.status === 'fail' ? 'Errore' : ''}>
                {line.status === 'ok' && 'OK'}
                {line.status === 'fail' && 'FAIL'}
              </span>
            </div>
          ))}
        </div>

        <div className={`boot-models ${bootDone ? 'visible' : ''}`}>
          {reachable === false && (
            <div style={{
              padding: 'var(--space-md)', background: 'var(--jeeg-amber-dim)',
              border: '1px solid rgba(245,166,35,0.3)', borderRadius: '4px',
              marginBottom: 'var(--space-md)', fontSize: 'var(--text-sm)', color: 'var(--jeeg-amber)',
            }}>
              Ollama non raggiungibile — mostro il catalogo dei modelli messi a disposizione. Le azioni sono disattivate.
            </div>
          )}
          {actionError && (
            <div style={{
              padding: 'var(--space-md)', background: 'var(--jeeg-red-dim)',
              border: '1px solid rgba(211,47,47,0.3)', borderRadius: '4px',
              marginBottom: 'var(--space-md)', fontSize: 'var(--text-sm)', color: 'var(--jeeg-red)',
            }}>
              {actionError}
            </div>
          )}

          <h3>Modelli messi a disposizione</h3>
          {catalog.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>Nessun modello configurato.</p>
          ) : catalog.map(model => {
            const isPulling = busy[`pull:${model.name}`]
            const isLoading = busy[`load:${model.name}`]
            const isUnloading = busy[`unload:${model.name}`]
            const isSelecting = busy[`select:${model.name}`]
            const working = isPulling || isLoading || isUnloading || isSelecting
            const prog = progress[model.name]
            return (
              <div key={model.name} className={`model-card ${model.active ? 'active' : ''}`}>
                <div className="model-info">
                  <div className="model-name">
                    {model.label || model.name}
                    {model.active && <span className="badge badge-ok" style={{ marginLeft: 8, fontSize: '0.6rem' }}>ATTIVO</span>}
                    {!model.active && model.downloaded && model.online && <span className="badge badge-info" style={{ marginLeft: 6, fontSize: '0.6rem' }}>IN LINEA</span>}
                    {!model.active && model.downloaded && !model.online && <span className="badge badge-warn" style={{ marginLeft: 6, fontSize: '0.6rem' }}>SCARICATO</span>}
                    {!model.downloaded && <span className="badge badge-error" style={{ marginLeft: 6, fontSize: '0.6rem' }}>NON SCARICATO</span>}
                  </div>
                  <div className="model-meta">
                    {model.family || 'Famiglia non definita'}
                    {formatSize(model.size_bytes) && ` · ${formatSize(model.size_bytes)}`}
                    {model.quantization && ` · ${model.quantization}`}
                  </div>
                  {model.description && <div className="model-description">{model.description}</div>}
                  {isPulling && (
                    <div className="model-progress">
                      <div className="model-progress-track">
                        <div className="model-progress-fill" style={{ width: `${Math.round((prog ? prog.progress : 0) * 100)}%` }} />
                      </div>
                      {prog && prog.message && <span className="model-progress-text">{prog.message}</span>}
                    </div>
                  )}
                </div>

                <div className="model-actions">
                  {!model.downloaded ? (
                    reachable && (
                      <button className="model-btn model-btn-pull" disabled={working} onClick={() => handlePull(model.name)} aria-label={`Scarica ${model.name}`}>
                        {isPulling ? 'Scaricando...' : 'Scarica'}
                      </button>
                    )
                  ) : (
                    <>
                      {!model.online ? (
                        <button className="model-btn model-btn-online" disabled={working || !reachable} onClick={() => handleLoad(model.name)} aria-label={`Mettere in linea ${model.name}`}>
                          {isLoading ? 'In corso...' : 'Mettere in linea'}
                        </button>
                      ) : (
                        <button className="model-btn model-btn-offline" disabled={working || !reachable} onClick={() => handleUnload(model.name)} aria-label={`Togli dalla linea ${model.name}`}>
                          {isUnloading ? 'In corso...' : 'Togli dalla linea'}
                        </button>
                      )}
                      {!model.active && (
                        <button className="model-btn model-btn-select" disabled={working || !reachable} onClick={() => handleSelect(model.name)} aria-label={`Seleziona ${model.name}`}>
                          {isSelecting ? '...' : 'Seleziona'}
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
