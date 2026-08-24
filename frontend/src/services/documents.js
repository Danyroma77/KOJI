/**
 * Servizio documenti — interfaccia reale con il backend.
 * Sostituisce l'uso dei mock data nel KB Manager.
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