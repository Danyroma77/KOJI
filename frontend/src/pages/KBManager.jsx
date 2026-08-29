// v20260827c - azioni per singolo documento: riprocessamento del file,
//              rigenerazione wiki e ri-estrazione grafo tramite nuovi job
//              indipendenti (endpoint POST /documents/{id}/reprocess,
//              /regenerate-wiki, /regenerate-graph). Il polling resta attivo
//              finché una di queste operazioni è in corso.

// v20260827b - vista sul file normalizzato: pulsante con icona cervello nella
//              tabella KB che apre il testo normalizzato (l'artefatto Markdown
//              prodotto dalla pipeline, origine dei chunk indicizzati), con
//              chip "Testo normalizzato" nell'header del visualizzatore e
//              pulsante disabilitato (con spiegazione nel tooltip) finché
//              l'artefatto non può esistere.

// v20260827 - tooltip sul badge di stato: al passaggio del mouse indica se il
//             documento è realmente indicizzato in ChromaDB (n. chunk
//             vettorizzati e data), il punto raggiunto dalla pipeline oppure,
//             in caso di errore, il messaggio completo.

// v20250622 - fix: null safety su tutte le proprietà dei documenti
import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Upload, Download, Trash2, FileText, FileCode,
  FileArchive, X, AlertCircle, CheckCircle, RefreshCw, Eye
} from 'lucide-react'
import {
  uploadDocuments, listDocuments, deleteDocument, deleteAllDocuments,
  downloadDocument, reprocessDocument, regenerateWiki, regenerateGraph,
  STATUS_MAP,
} from '../services/documents'
import { Brain, BookOpen, Share2 } from 'lucide-react'

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

/**
 * Testo mostrato al passaggio del mouse sull'etichetta di stato.
 * Dichiara esplicitamente se il documento è stato indicizzato
 * (chunk+embedding inseriti in ChromaDB) o perché no.
 */
function statusTooltip(doc, st) {
  var label = st && st.label ? st.label : String(doc.status || 'N/D')
  switch (String(doc.status || '')) {
    case 'uploaded':
      return 'File caricato e accodato per il processing: NON ancora indicizzato'
    case 'parsing':
      return 'Estrazione del testo dal file in corso: NON ancora indicizzato'
    case 'normalizing':
      return 'Normalizzazione del testo in corso: NON ancora indicizzato'
    case 'chunking':
      return 'Suddivisione del testo in chunk in corso: NON ancora indicizzato'
    case 'embedding':
      return 'Vettorizzazione dei chunk in corso: NON ancora indicizzato'
    case 'error':
      var msg = String(doc.error_message || '').trim()
      return msg
        ? 'Elaborazione fallita, documento NON indicizzato. Motivo: ' + msg
        : 'Elaborazione fallita: documento NON indicizzato'
    case 'ready':
      var chunks = doc.chunks_count
      if (chunks != null && Number(chunks) > 0) {
        var when = doc.updated_at
          ? new Date(doc.updated_at).toLocaleString('it-IT')
          : ''
        return 'Documento INDICIZZATO in ChromaDB: ' + chunks +
          ' chunk vettorizzati' + (when ? ' · ' + when : '')
      }
      // Stato "pronto" ma zero chunk: segnalazione anomalia
      return 'Attenzione: stato "Pronto" ma 0 chunk in ChromaDB — indicizzazione non verificabile'
    default:
      return 'Stato documento: ' + label
  }
}

/**
 * Il file normalizzato viene salvato su disco durante l'elaborazione, dopo la
 * normalizzazione: a partire dalla fase di chunking il suo contenuto è quindi
 * garantito (lo stato resta 'normalizing' solo per pochi istanti). Nei primi
 * stati la vista sarebbe vuota: teniamo il pulsante disabilitato.
 */
function canViewNormalized(status) {
  var s = String(status || '')
  return s === 'chunking' || s === 'embedding' || s === 'ready' || s === 'error'
}

/**
 * Tooltip del pulsante cervello: spiega cosa contiene la vista normalizzata
 * e perché il pulsante può risultare disabilitato.
 */
function normalizedViewTitle(doc) {
  if (!canViewNormalized(doc.status)) {
    var lbl = (STATUS_MAP[String(doc.status)] || {}).label || String(doc.status)
    return 'File normalizzato non ancora disponibile: viene creato durante l\'elaborazione (stato attuale: ' + lbl + ')'
  }
  var base = 'Apri il file normalizzato prodotto dalla pipeline: il testo pulito in Markdown da cui derivano i chunk indicizzati'
  var chunks = doc.chunks_count
  if (String(doc.status) === 'ready' && chunks != null && Number(chunks) > 0) {
    return base + ' · ' + Number(chunks) + ' chunk'
  }
  return base
}

/**
 * Il riprocessamento riparte dal file raw già su disco: è consentito quando
 * il documento è stabile (pronto, errore o in attesa di processing) ma non
 * mentre una fase di parsing/chunking/embedding è già in corso.
 */
function canReprocess(status) {
  var s = String(status || '')
  return s === 'ready' || s === 'error' || s === 'uploaded'
}

function reprocessTitle(doc, active) {
  if (active) return 'Riprocessamento già accodato: in attesa di esito'
  if (!canReprocess(doc.status)) {
    var lbl = (STATUS_MAP[String(doc.status)] || {}).label || String(doc.status)
    return 'Non riprocessabile ora: elaborazione già in corso (stato: ' + lbl + ')'
  }
  return 'Riprocessa il file: nuovo parsing, chunking, indicizzazione, wiki e grafo dal file originale'
}

function wikiTitle(doc, active) {
  if (active) return 'Rigenerazione wiki già accodata: in attesa di esito'
  if (!canViewNormalized(doc.status)) {
    return 'Wiki non generabile: serve prima il testo normalizzato (elaborazione non ancora sufficientemente avanzata)'
  }
  return 'Rigenera la wiki a partire dai documenti pronti (include questo documento)'
}

function graphTitle(doc, active) {
  if (active) return 'Estrazione grafo già accodata: in attesa di esito'
  if (!canViewNormalized(doc.status)) {
    return 'Grafo non estraibile: serve prima il testo normalizzato (elaborazione non ancora sufficientemente avanzata)'
  }
  var last = doc.graph_updated_at
    ? ' · ultima estrazione ' + new Date(doc.graph_updated_at).toLocaleString('it-IT')
    : ' · mai estratto'
  return 'Ri-estrae entità e relazioni di questo documento tramite LLM' + last
}


export default function KBManager() {
  const [docs, setDocs] = useState([])
  const [totalChunks, setTotalChunks] = useState(0)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [message, setMessage] = useState(null)
  const [messageType, setMessageType] = useState('info')
  const fileInputRef = useRef(null)
  const pollRef = useRef(null)
  const [viewingDoc, setViewingDoc] = useState(null)
  const viewerRef = useRef(null)

  // Operazioni per-documento accodate di recente (reprocess/wiki/grafo):
  // mappa docId -> timestamp della richiesta. Mantiene il polling attivo
  // finché il job non produce esito (o scade la finestra di osservazione).
  const [regenPending, setRegenPending] = useState({})
  const REGEN_WATCH_WINDOW = 180000 // 3 minuti

  function markRegen(docId) {
    setRegenPending(function(prev) {
      var next = Object.assign({}, prev)
      next[docId] = Date.now()
      return next
    })
  }

  function hasFreshRegen() {
    var now = Date.now()
    for (var k in regenPending) {
      if (now - regenPending[k] < REGEN_WATCH_WINDOW) return true
    }
    return false
  }

  function regenActive(docId) {
    var ts = regenPending[docId]
    return Boolean(ts) && (Date.now() - ts < REGEN_WATCH_WINDOW)
  }

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
            wiki_updated_at: d.wiki_updated_at || null,
            graph_updated_at: d.graph_updated_at || null,
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
      if (hasProcessing || hasFreshRegen()) fetchDocs()
    }, 3000)
    return function() {
      clearTimeout(initialFetch)
      if (pollRef.current) clearInterval(pollRef.current)
      clearInterval(interval)
    }
  }, [docs, fetchDocs, regenPending])

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

  function handleClearAll() {
    var n = docs.length
    if (n === 0) {
      showMsg('La Knowledge Base è già vuota', 'info')
      return
    }
    var msg = 'Svuotare la Knowledge Base? Verranno eliminati TUTTI i ' + n +
      ' documenti con i loro chunk, embedding e pagine wiki. Operazione irreversibile.'
    if (!confirm(msg)) return
    setClearing(true)
    deleteAllDocuments().then(function(result) {
      showMsg('KB svuotata: ' + String(result.removed) + ' documento/i rimossi', 'success')
      setViewingDoc(null)
      fetchDocs()
    }).catch(function(err) {
      console.error(err)
      showMsg(String(err.message), 'error')
    }).finally(function() {
      setClearing(false)
    })
  }

  async function handleDownload(docId) {
    downloadDocument(docId).catch(function(err) {
      console.error(err)
      showMsg(String(err.message), 'error')
    })
  }

  // ==== Azioni per singolo documento: riprocessa / wiki / grafo ====

  function handleReprocess(doc) {
    if (!canReprocess(doc.status) || regenActive(doc.id)) return
    if (!confirm('Riprocessare "' + doc.filename + '"? Chunk, grafo e testo normalizzato attuali verranno ricostruiti.')) return
    reprocessDocument(doc.id).then(function(result) {
      showMsg(String(result.message || 'Riprocessamento accodato'), 'success')
      markRegen(doc.id)
      fetchDocs()
    }).catch(function(err) {
      console.error(err)
      showMsg(String(err.message), 'error')
    })
  }

  function handleRegenWiki(doc) {
    if (!canViewNormalized(doc.status) || regenActive(doc.id)) return
    regenerateWiki(doc.id).then(function(result) {
      showMsg(String(result.message || 'Rigenerazione wiki accodata'), 'success')
      markRegen(doc.id)
    }).catch(function(err) {
      console.error(err)
      showMsg(String(err.message), 'error')
    })
  }

  function handleRegenGraph(doc) {
    if (!canViewNormalized(doc.status) || regenActive(doc.id)) return
    regenerateGraph(doc.id).then(function(result) {
      showMsg(String(result.message || 'Estrazione grafo accodata'), 'success')
      markRegen(doc.id)
    }).catch(function(err) {
      console.error(err)
      showMsg(String(err.message), 'error')
    })
  }

  async function handleView(docId, normalizedMode) {
    try {
      // Usa il testo estratto dalla pipeline (leggibile per ogni formato),
      // non il file originale che per PDF/DOCX è binario.
      var res = await fetch('/api/documents/' + String(docId) + '/text')
      if (!res.ok) {
        var errDetail = 'Testo non disponibile'
        try {
          var errJson = await res.json()
          errDetail = errJson.detail || errDetail
        } catch (e) { /* risposta non JSON */ }
        throw new Error(errDetail)
      }
      var text = await res.text()
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
        normalized: Boolean(normalizedMode),
      })
    } catch (err) {
      console.error(err)
      showMsg((normalizedMode ? 'File normalizzato non ancora disponibile: ' : 'Impossibile leggere il documento: ') + String(err.message), 'error')
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
    <div className="animate-fade-in kb-page" aria-label="Knowledge Base Manager">
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

      <div
        className="kb-toolbar"
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 'var(--space-sm)', flexWrap: 'wrap' }}
      >
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
        <button
          className="admin-btn admin-btn-secondary kb-clear-btn"
          style={{ fontSize: 'var(--text-xs)', padding: '6px 12px', color: 'var(--jeeg-red)' }}
          onClick={handleClearAll}
          disabled={clearing || docs.length === 0}
          title="Elimina tutti i documenti dalla Knowledge Base"
          aria-label="Svuota la Knowledge Base"
        >
          <Trash2 size={12} style={{ verticalAlign: '-2px', marginRight: '4px' }} />
          {clearing ? 'Svuotamento...' : 'Svuota KB'}
        </button>
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
                  <th scope="col" style={{ width: '140px' }}>Azioni</th>
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
                        <span className={'badge ' + st.cls}
                          title={statusTooltip(doc, st)}
                          aria-label={statusTooltip(doc, st)}>
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
                            onClick={function() { handleView(doc.id, true) }}
                            title={normalizedViewTitle(doc)}
                            aria-label="Vista sul file normalizzato"
                            disabled={!canViewNormalized(doc.status)}>
                            <Brain size={14} />
                          </button>
                          <button className="kb-action-btn"
                            onClick={function() { handleReprocess(doc) }}
                            title={reprocessTitle(doc, regenActive(doc.id))}
                            aria-label="Riprocessa documento"
                            disabled={!canReprocess(doc.status) || regenActive(doc.id)}>
                            <RefreshCw size={14} />
                          </button>
                          <button className="kb-action-btn"
                            onClick={function() { handleRegenWiki(doc) }}
                            title={wikiTitle(doc, regenActive(doc.id))}
                            aria-label="Rigenera wiki"
                            disabled={!canViewNormalized(doc.status) || regenActive(doc.id)}>
                            <BookOpen size={14} />
                          </button>
                          <button className="kb-action-btn"
                            onClick={function() { handleRegenGraph(doc) }}
                            title={graphTitle(doc, regenActive(doc.id))}
                            aria-label="Rigenera grafo"
                            disabled={!canViewNormalized(doc.status) || regenActive(doc.id)}>
                            <Share2 size={14} />
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
                {viewingDoc.normalized && (
                  <span
                    className="kb-viewer-mode"
                    title="Contenuto del file normalizzato salvato su disco dall'elaborazione"
                  >
                    <Brain size={12} style={{ verticalAlign: '-2px', marginRight: 4 }} aria-hidden="true" />
                    Testo normalizzato
                  </span>
                )}
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