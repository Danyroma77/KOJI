// Servizio API per il backend FastAPI
// In produzione, sostituire i mock con chiamate reali

const API_BASE = '/api'

export async function getSystemStatus() {
  try {
    const res = await fetch(`${API_BASE}/system/status`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch {
    return null
  }
}

export async function getDocuments() {
  try {
    const res = await fetch(`${API_BASE}/documents`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch {
    return null
  }
}

export async function uploadDocuments(files) {
  const formData = new FormData()
  files.forEach(f => formData.append('files', f))

  const res = await fetch(`${API_BASE}/documents/upload`, {
    method: 'POST',
    body: formData
  })
  return res.json()
}

export async function deleteDocument(docId) {
  const res = await fetch(`${API_BASE}/documents/${docId}`, {
    method: 'DELETE'
  })
  return res.json()
}

export async function getGraph() {
  try {
    const res = await fetch(`${API_BASE}/graph`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch {
    return null
  }
}

export async function getMetrics() {
  try {
    const res = await fetch(`${API_BASE}/system/metrics`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch {
    return null
  }
}