/**
 * =============================================================================
 * SERVIZIO DOCUMENTI — INTERFACCIA CON IL BACKEND PER GESTIONE DOCUMENTI
 * =============================================================================
 * 
 * Fornisce funzioni per gestire i documenti nella Knowledge Base.
 * Include upload, download, eliminazione, riprocessamento e cronologia.
 * 
 * ENDPOINT DISPONIBILI:
 * - POST   /api/documents/upload              → Carica nuovi documenti
 * - GET    /api/documents                     → Lista documenti
 * - DELETE /api/documents/{id}                → Elimina documento
 * - DELETE /api/documents/all                 → Svuota KB completa
 * - GET    /api/documents/{id}/download       → Download file originale
 * - GET    /api/documents/jobs                → Lista job di processing
 * - POST   /api/documents/{id}/reprocess      → Riprocessa documento
 * - POST   /api/documents/{id}/regenerate-wiki → Rigenera wiki
 * - POST   /api/documents/{id}/regenerate-graph → Rigenera grafo
 * - GET    /api/documents/activities          → Cronologia attività
 */

const API_BASE = '/api/documents'

export async function uploadDocuments(files) {
  const formData = new FormData()
  for (const f of files) {
    formData.append('files', f)
  }

  const res = await fetch(`${API_BASE}/upload`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Errore upload: ${res.status}`)
  }

  return res.json()
}

export async function listDocuments() {
  const res = await fetch(API_BASE)
  if (!res.ok) throw new Error(`Errore lista: ${res.status}`)
  return res.json()
}

export async function deleteDocument(docId) {
  const res = await fetch(`${API_BASE}/${docId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Errore cancellazione: ${res.status}`)
  return res.json()
}

/**
 * Svuota interamente la Knowledge Base: rimuove tutti i documenti
 * con i loro chunk, embedding, nodi del grafo e pagine wiki.
 */
export async function deleteAllDocuments() {
  const res = await fetch(`${API_BASE}/all`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Errore svuotamento KB: ${res.status}`)
  }
  return res.json()
}

export async function downloadDocument(docId) {
  const res = await fetch(`${API_BASE}/${docId}/download`)
  if (!res.ok) throw new Error(`Errore download: ${res.status}`)

  const header = res.headers.get('Content-Disposition')
  let filename = 'documento'
  if (header) {
    const match = header.match(/filename="?([^"]+)"?/)
    if (match) filename = match[1]
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export async function listJobs() {
  const res = await fetch(`${API_BASE}/jobs`)
  if (!res.ok) return []
  return res.json()
}

/**
 * Richiede il riprocessamento del file originale (parsing → normalizzazione
 * → chunking → embedding → wiki/grafo) senza nuovo upload.
 */
export async function reprocessDocument(docId) {
  const res = await fetch(`${API_BASE}/${docId}/reprocess`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Errore riprocessamento: ${res.status}`)
  }
  return res.json()
}

/**
 * Accoda la rigenerazione della wiki (globale) a partire dal documento indicato.
 */
export async function regenerateWiki(docId) {
  const res = await fetch(`${API_BASE}/${docId}/regenerate-wiki`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Errore wiki: ${res.status}`)
  }
  return res.json()
}

/**
 * Accoda la ri-estrazione del grafo di conoscenza per il singolo documento.
 */
export async function regenerateGraph(docId) {
  const res = await fetch(`${API_BASE}/${docId}/regenerate-graph`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Errore grafo: ${res.status}`)
  }
  return res.json()
}

/**
 * Cronologia delle attività sulla KB, con paginazione server-side.
 * Include upload, modifiche (sovrascrittura file esistente), eliminazioni
 * ed esiti del processing (indicizzato / errore).
 *
 * `limit` e `offset` sono opzionali: con l'immagine API precedente l'extra
 * query param `offset` viene ignorato da FastAPI e restano validi i limiti
 * fino a 50, quindi la funzione resta compatibile in entrambi i casi.
 */
export async function listActivities(limit = 20, offset = 0) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  const res = await fetch(`${API_BASE}/activities?${params.toString()}`)
  if (!res.ok) throw new Error(`Errore attività: ${res.status}`)
  return res.json()
}

/**
 * Mappa stato dal backend al formato frontend.
 */
export const STATUS_MAP = {
  uploaded:    { label: 'Caricato', cls: 'badge-info', icon: '↑' },
  parsing:     { label: 'Parsing', cls: 'badge-warn', icon: '⟳' },
  normalizing: { label: 'Normalizzazione', cls: 'badge-warn', icon: '⟳' },
  chunking:    { label: 'Chunking', cls: 'badge-warn', icon: '⟳' },
  embedding:   { label: 'Embedding', cls: 'badge-warn', icon: '⟳' },
  ready:       { label: 'Pronto', cls: 'badge-ok', icon: '✓' },
  error:       { label: 'Errore', cls: 'badge-error', icon: '✗' },
}