// Servizio di interfaccia con Ollama
// Tutte le chiamate puntano a /ollama/* che il proxy di Vite
// reindirizza a localhost:11434

const OLLAMA_BASE = '/ollama'

export async function listModels() {
  try {
    const res = await fetch(`${OLLAMA_BASE}/api/tags`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    return data.models || []
  } catch (err) {
    console.warn('Impossibile raggiungere Ollama:', err.message)
    return null
  }
}

export async function showModel(name) {
  const res = await fetch(`${OLLAMA_BASE}/api/show`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  })
  return res.json()
}

export async function generate(prompt, model, options = {}) {
  const res = await fetch(`${OLLAMA_BASE}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      prompt,
      stream: false,
      options: {
        temperature: options.temperature ?? 0.3,
        top_k: options.topK ?? 40,
        num_predict: options.maxTokens ?? 512,
      }
    })
  })
  return res.json()
}

// Generazione con streaming — restituisce un ReadableStream
export function generateStream(prompt, model, options = {}) {
  return fetch(`${OLLAMA_BASE}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      prompt,
      stream: true,
      options: {
        temperature: options.temperature ?? 0.3,
        top_k: options.topK ?? 40,
        num_predict: options.maxTokens ?? 512,
      }
    })
  })
}

export async function checkHealth() {
  try {
    const res = await fetch(`${OLLAMA_BASE}/api/tags`, { signal: AbortSignal.timeout(3000) })
    return res.ok
  } catch {
    return false
  }
}