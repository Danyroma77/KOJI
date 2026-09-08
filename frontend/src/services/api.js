/**
 * =============================================================================
 * SERVIZIO API — INTERFACCIA CON IL BACKEND FASTAPI
 * =============================================================================
 * 
 * Questo modulo fornisce funzioni per comunicare con il backend.
 * Tutte le chiamate usano fetch API con gestione errori base.
 * 
 * ENDPOINT DISPONIBILI:
 * - GET  /api/system/status    → Stato dei servizi
 * - GET  /api/documents        → Lista documenti
 * - POST /api/documents/upload → Upload documenti
 * - DELETE /api/documents/{id} → Elimina documento
 * - GET  /api/graph            → Knowledge Graph
 * - GET  /api/system/metrics   → Metriche di sistema
 * 
 * GESTIONE ERRORI:
 * - Ogni funzione try/catch con fallback a null
 * - Log errori in console per debug
 */

// Base URL per tutte le chiamate API
const API_BASE = '/api'

/**
 * Ottiene lo stato dei servizi backend.
 * 
 * @returns {Promise<Object|null} Stato servizi o null in caso di errore
 */
export async function getSystemStatus() {
  try {
    const res = await fetch(`${API_BASE}/system/status`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch {
    return null
  }
}

/**
 * Ottiene la lista dei documenti nella Knowledge Base.
 * 
 * @returns {Promise<Object|null} Lista documenti o null in caso di errore
 */
export async function getDocuments() {
  try {
    const res = await fetch(`${API_BASE}/documents`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch {
    return null
  }
}

/**
 * Carica nuovi documenti nella Knowledge Base.
 * 
 * @param {FileList|Array} files - File da caricare
 * @returns {Promise<Object>} Risposta del backend
 */
export async function uploadDocuments(files) {
  const formData = new FormData()
  files.forEach(f => formData.append('files', f))

  const res = await fetch(`${API_BASE}/documents/upload`, {
    method: 'POST',
    body: formData
  })
  return res.json()
}

/**
 * Elimina un documento dalla Knowledge Base.
 * 
 * @param {string} docId - ID del documento da eliminare
 * @returns {Promise<Object>} Risposta del backend
 */
export async function deleteDocument(docId) {
  const res = await fetch(`${API_BASE}/documents/${docId}`, {
    method: 'DELETE'
  })
  return res.json()
}

/**
 * Ottiene il Knowledge Graph completo.
 * 
 * @returns {Promise<Object|null} Grafo (nodi e archi) o null in caso di errore
 */
export async function getGraph() {
  try {
    const res = await fetch(`${API_BASE}/graph`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch {
    return null
  }
}

/**
 * Ottiene le metriche di sistema.
 * 
 * @returns {Promise<Object|null} Metriche o null in caso di errore
 */
export async function getMetrics() {
  try {
    const res = await fetch(`${API_BASE}/system/metrics`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  } catch {
    return null
  }
}