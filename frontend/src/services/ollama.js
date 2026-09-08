/**
 * =============================================================================
 * SERVIZIO OLLAMA — INTERFACCIA CON IL SERVER OLLAMA (DEPRECATO)
 * =============================================================================
 * 
 * Questo servizio è mantenuto per compatibilità ma le chiamate dirette
 * a Ollama sono state sostituite dalle API del backend FastAPI.
 * 
 * Le chiamate puntano a /ollama/* che il proxy di Vite
 * reindirizza a localhost:11434.
 * 
 * FUNZIONI DISPONIBILI:
 * - listModels: lista modelli installati in Ollama
 * - showModel: dettagli di un modello
 * - generate: generazione testo (non streaming)
 * - generateStream: generazione testo (streaming)
 * - checkHealth: verifica connettività OllAMA
 * 
 * NOTA: Le funzioni di generate sono usate principalmente per test.
 * L'applicazione usa principalmente le API del backend per le operazioni RAG.
 */

const OLLAMA_BASE = '/ollama'

/**
 * Lista i modelli installati in Ollama.
 * 
 * @returns {Promise<Array|null} Lista modelli o null in caso di errore
 */
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

/**
 * Ottiene i dettagli di un modello specifico.
 * 
 * @param {string} name - Nome del modello
 * @returns {Promise<Object>} Dettagli del modello
 */
export async function showModel(name) {
  const res = await fetch(`${OLLAMA_BASE}/api/show`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  })
  return res.json()
}

/**
 * Genera testo con un modello (non streaming).
 * 
 * @param {string} prompt - Prompt per la generazione
 * @param {string} model - Nome del modello da usare
 * @param {Object} options - Opzioni (temperature, topK, maxTokens)
 * @returns {Promise<Object>} Risposta della generazione
 */
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

/**
 * Genera testo con streaming (ritorna ReadableStream).
 * 
 * @param {string} prompt - Prompt per la generazione
 * @param {string} model - Nome del modello da usare
 * @param {Object} options - Opzioni (temperature, topK, maxTokens)
 * @returns {Promise<Response>} Response con stream di dati
 */
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

/**
 * Verifica la connettività con Ollama.
 * 
 * @returns {Promise<boolean>} true se Ollama è raggiungibile
 */
export async function checkHealth() {
  try {
    const res = await fetch(`${OLLAMA_BASE}/api/tags`, { signal: AbortSignal.timeout(3000) })
    return res.ok
  } catch {
    return false
  }
}