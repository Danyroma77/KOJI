// v20250622 - fix: null safety su tutte le proprietà dei documenti
import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Upload, Download, Trash2, FileText, FileCode,
  FileArchive, X, AlertCircle, CheckCircle, RefreshCw, Eye
} from 'lucide-react'
import { uploadDocuments, listDocuments, deleteDocument, downloadDocument, STATUS_MAP } from '../services/documents'

const FORMAT_ICONS = {
  pdf: FileText,
  docx: FileText,
  doc: FileText,
  odt: FileText,
  html: FileCode,
  md: FileCode,
  eml: FileArchive,
  txt: FileCode,
}

function getFileIcon(format) {
  var key = String(format || '').toLowerCase().replace('.', '')
  return FORMAT_ICONS[key] || FileText
}

export default function KBManager() {
  const [docs, setDocs] = useState([])
  const [totalChunks, setTotalChunks] = useState(0)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [message, setMessage] = useState(null)
  const [messageType, setMessageType] = useState('info')
  const fileInputRef = useRef(null)
  const pollRef = useRef(null)
  const [viewingDoc, setViewingDoc] = useState(null)
  const viewerRef = useRef(null)

  const fetchDocs = useCallback(async function() {
    try {
      var data = await listDocuments()
      var safeDocs = []
      if (data.documents && Array.isArray(data.documents)) {
        for (var i = 0; i < data.documents.length; i++) {
          var d = data.documents[i]
          safeDocs.push({
            id: d.id,
            filename: d.filename || 'documento',
            error_message: d.error_message || '',
            format: d.format || 'N/D',
            chunks_count: d.chunks_count,
            status: d.status,
            updated_at: d.updated_at || null,
          })
        }
      }
      setDocs(safeDocs)
      if (data.total_chunks) setTotalChunks(data.total_chunks)
    } catch (err) {
      console.error(err)
    } finally {
    setLoading(false)
  }
  }, [])

  useEffect(function() {
    var initialFetch = setTimeout(function() {
      fetchDocs()
    }, 0)
    var interval = setInterval(function() {
      var hasProcessing = false
      if (docs && Array.isArray(docs)) {
        for (var i = 0; i < docs.length; i++) {
          var s = docs[i].status
          if (s !== 'ready' && s !== 'error') {
            hasProcessing = true
            break
          }
        }
      }
      if (hasProcessing) fetchDocs()
    }, 3000)
    return function() {
      clearTimeout(initialFetch)
      if (pollRef.current) clearInterval(pollRef.current)
      clearInterval(interval)
    }
  }, [docs, fetchDocs])

  function showMsg(text, type) {
    setMessage(text)
    setMessageType(type)
    setTimeout(function() { setMessage(null) }, 5000)
  }

  function handleFiles(files) {
    if (!files || files.length === 0) return
    setUploading(true)
    try {
      uploadDocuments(files).then(function(result) {
        var uploadedCount = String(result.uploaded.length)
        var errorCount = String(result.errors.length)
        if (errorCount !== '0') {
          showMsg(errorCount + ' errori su ' + String(files.length) + ' file', 'error')
        } else {
          showMsg(uploadedCount + ' documento/i accodati per il processing', 'success')
        }
        fetchDocs()
      }).catch(function(err) {
        console.error(err)
        showMsg(String(err.message), 'error')
      })
    } finally {
      setUploading(false)
    }
  }

  function handleDragOver(e) { e.preventDefault(); setDragOver(true) }
  function handleDragLeave() { setDragOver(false) }
  function handleDrop(e) {
    e.preventDefault()
    setDragOver(false)
    handleFiles(Array.from(e.dataTransfer.files))
  }
  function handleFileSelect(e) {
    handleFiles(Array.from(e.target.files))
    e.target.value = ''
  }

  function handleDelete(docId, filename) {
    var safeName = String(filename || 'documento')
    if (!confirm('Eliminare ' + safeName + '? L operazione e irreversibile.')) return
    deleteDocument(docId).then(function() {
      showMsg(safeName + ' eliminato', 'success')
      if (viewingDoc && viewingDoc.id === docId) setViewingDoc(null)
      fetchDocs()
    }).catch(function(err) {
      console.error(err)
      showMsg(String(err.message), 'error')
    })
  }

  async function handleDownload(docId) {
    downloadDocument(docId).catch(function(err) {
      console.error(err)
      showMsg(String(err.message), 'error')
    })
  }

  async function handleView(docId) {
    try {
      var res = await fetch('/api/documents/' + String(docId) + '/download')
      if (!res.ok) throw new Error('File non disponibile')
      var blob = await res.blob()
      var text = await blob.text()
      var doc = null
      if (docs && Array.isArray(docs)) {
        for (var i = 0; i < docs.length; i++) {
          if (docs[i].id === docId) {
            doc = docs[i]
            break
          }
        }
      }
      setViewingDoc({
        id: docId,
        filename: doc ? doc.filename : 'documento',
        content: text,
      })
    } catch (err) {
      console.error(err)
      showMsg('Impossibile leggere il documento: ' + String(err.message), 'error')
    }
  }

  function closeViewer() {
    setViewingDoc(null)
  }

  useEffect(function() {
    if (!viewingDoc) return
    function handleKeyDown(e) {
      if (e.key === 'Escape') closeViewer()
    }
    document.addEventListener('keydown', handleKeyDown)
    return function() {
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [viewingDoc])

  var processingCount = 0
  if (docs && Array.isArray(docs)) {
    for (var i = 0; i < docs.length; i++) {
      var s = docs[i].status
      if (s !== 'ready' && s !== 'error') {
        processingCount++
      }
    }
  }

  return (
    <div className="animate-fade-in" aria-label="Knowledge Base Manager">
      <div className="kb-header">
        <h2>Knowledge Base</h2>
        <p className="motto">La conoscenza non viene derivata, viene organizzata</p>
        <p className="kb-stats">
          {docs.length} documenti · {totalChunks.toLocaleString()} chunk
          {processingCount > 0 && (
            <span className="badge badge-warn" style={{ marginLeft: 8 }}>
              {processingCount} in elaborazione
            </span>
          )}
        </p>
      </div>

      {message && (
        <div className={'upload-message upload-message-' + messageType} role="alert">
          {messageType === 'error' ? <AlertCircle size={16} /> : <CheckCircle size={16} />}
          {message}
        </div>
      )}

      <div
        className={'kb-upload' + (dragOver ? 'dragover' : '') + (uploading ? 'uploading' : '')}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={function() { if (!uploading) fileInputRef.current && fileInputRef.current.click() }}
        role="button"
        tabIndex={0}
        aria-label="Area di caricamento documenti"
        onKeyDown={function(e) { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current.click() }}
      >
        <Upload className="kb-upload-icon" aria-hidden="true" />
        {uploading ? (
          <div className="kb-upload-text">Caricamento in corso...</div>
        ) : (
          <>
            <div className="kb-upload-text">Trascina qui i file o clicca per caricare</div>
            <div className="kb-upload-formats">PDF - DOCX - ODT - HTML - MD - EML - TXT</div>
          </>
        )}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.odt,.html,.md,.eml,.txt"
          onChange={handleFileSelect}
          className="sr-only"
          aria-hidden="true"
        />
      </div>

      <div className="kb-toolbar">
        <div style={{ display: 'flex', gap: 'var(--space-sm)', alignItems: 'center' }}>
          <label htmlFor="kb-filter" className="sr-only">Filtra per stato</label>
          <select id="kb-filter" className="rag-select" aria-label="Filtra documenti per stato">
            <option value="">Tutti gli stati</option>
            <option value="ready">Pronto</option>
            <option value="error">Errore</option>
          </select>
          <button
            className="admin-btn admin-btn-secondary"
            style={{ fontSize: 'var(--text-xs)', padding: '6px 12px' }}
            onClick={fetchDocs}
            aria-label="Aggiorna lista"
          >
            <RefreshCw size={12} style={{ verticalAlign: '-2px', marginRight: '4px' }} />
            Aggiorna
          </button>
        </div>
      </div>

      <div className="kb-table-layout">
        <div className="kb-table-wrap" style={{ borderRadius: '8px' }}>
          {loading ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
              Caricamento in corso...
            </div>
          ) : docs.length === 0 ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
              <FileText size={32} style={{ display: 'block', margin: '0 auto 1rem', opacity: 0.25 }} />
              Nessun documento nella Knowledge Base.
              <br />Carica i tuoi primi documenti sopra.
            </div>
          ) : (
            <table className="kb-table" aria-label="Elenco documenti">
              <thead>
                <tr>
                  <th scope="col" style={{ width: '40%' }}>Nome</th>
                  <th scope="col" style={{ width: '70px' }}>Tipo</th>
                  <th scope="col" style={{ width: '120px' }}>Stato</th>
                  <th scope="col" style={{ width: '70px' }}>Chunk</th>
                  <th scope="col" style={{ width: '100px' }}>Aggiornato</th>
                  <th scope="col" style={{ width: '100px' }}>Azioni</th>
                </tr>
              </thead>
              <tbody>
                {docs.map(function(doc) {
                  var st = STATUS_MAP[doc.status] || STATUS_MAP.ready
                  var Icon = getFileIcon(doc.format)
                  return (
                    <tr key={doc.id} className={doc.error_message ? 'row-error' : ''}>
                      <td className="doc-name">
                        <Icon size={15} style={{
                          display: 'inline', verticalAlign: 'middle',
                          marginRight: 8, opacity: 0.5, flexShrink: 0,
                          color: 'var(--jeeg-green)',
                        }} aria-hidden="true" />
                        <span>{doc.filename}</span>
                        {doc.error_message && (
                          <span className="doc-error-tip" title={doc.error_message}> ATTENZIONE</span>
                        )}
                      </td>
                      <td><span className="format-badge">{doc.format || 'N/D'}</span></td>
                      <td>
                        <span className={'badge ' + st.cls}>
                          <span className="badge-dot" aria-hidden="true" />
                          {st.icon} {st.label}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-sm)', textAlign: 'center' }}>
                        {doc.chunks_count != null ? doc.chunks_count : '—'}
                      </td>
                      <td style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
                        {doc.updated_at ? new Date(doc.updated_at).toLocaleDateString('it-IT') : '—'}
                      </td>
                      <td>
                        <div className="actions-cell">
                          <button className="kb-action-btn"
                            onClick={function() { handleView(doc.id) }}
                            title="Visualizza">
                            <Eye size={14} />
                          </button>
                          <button className="kb-action-btn"
                            onClick={function() { handleDownload(doc.id) }}
                            title="Scarica">
                            <Download size={14} />
                          </button>
                          <button className="kb-action-btn danger"
                            onClick={function() { handleDelete(doc.id, doc.filename) }}
                            title="Elimina">
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {viewingDoc && (
        <div className="kb-viewer-overlay" onClick={closeViewer}>
          <div
            className="kb-viewer kb-viewer-open kb-viewer-modal"
            role="dialog"
            aria-modal="true"
            aria-label={'Visualizzazione documento ' + viewingDoc.filename}
            onClick={function(e) { e.stopPropagation() }}
          >
            <div className="kb-viewer-header">
              <div>
                <span className="kb-viewer-filename">{viewingDoc.filename}</span>
                <span className="kb-viewer-meta">
                  {viewingDoc.content.split('\n').filter(function(l) { return l.trim().length > 0 }).length} righe ·
                  {(viewingDoc.content.length / 1024).toFixed(1)} KB
                </span>
              </div>
              <button className="kb-viewer-close" onClick={closeViewer} aria-label="Chiudi visualizzatore">
                <X size={18} />
              </button>
            </div>
            <div className="kb-viewer-body" ref={viewerRef}>
              <pre>{viewingDoc.content}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
)
  }