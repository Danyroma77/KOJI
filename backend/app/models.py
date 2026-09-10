"""
=============================================================================
MODELLI PYDANTIC PER VALIDAZIONE RICHIESTA/RISPOSTA
=============================================================================

Questo modulo definisce tutti i modelli dati usati dall'API per:
- Validazione automatica dei dati in ingresso/uscita
- Serializzazione JSON
- Documentazione OpenAPI generata automatica

ORGANIZZAZIONE:
1. Enumerazioni (stati, formati, azioni)
2. Modelli documenti (catalogo, metadati, risposte)
3. Modelli attività (cronologia KB)
4. Modelli RAG (query, risposta, risultati)
5. Modelli Knowledge Graph (nodi, archi, dettagli)
6. Modelli Wiki (pagine, indice)
7. Modelli Job (stato, progresso, risultati)
8. Modelli ricerca (query, risultati)
9. Modelli Benchmark (esperimenti, configurazione)
10. Modelli amministrazione (configurazione, metriche)

GARANZIE PYDANTIC:
- Validazione tipo dato
- Vincoli (min, max, regex)
- Documentazione campi
- Default values
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


# =============================================================================
# ENUMERAZIONI
# =============================================================================

class DocumentStatus(str, Enum):
    """
    Stati del ciclo di vita di un documento nella pipeline di processing.
    
    Flusso normale: UPLOADED → PARSING → NORMALIZING → CHUNKING → EMBEDDING → READY
    In caso di errore: qualsiasi stato → ERROR
    """
    UPLOADED = "uploaded"      # Caricato, in attesa di processing
    PARSING = "parsing"        # Estrazione testo in corso
    NORMALIZING = "normalizing"  # Normalizzazione testo in corso
    CHUNKING = "chunking"      # Suddivisione in chunk
    EMBEDDING = "embedding"    # Generazione embedding
    READY = "ready"            # Indicizzato e disponibile
    ERROR = "error"            # Errore durante il processing


class DocumentFormat(str, Enum):
    """Formati di documento supportati dalla piattaforma."""
    PDF = "pdf"
    DOCX = "docx"
    ODT = "odt"
    HTML = "html"
    MARKDOWN = "md"
    EMAIL = "eml"
    TEXT = "txt"


# === Documenti ===

class DocumentUploadResponse(BaseModel):
    """Risposta dopo upload documenti."""
    uploaded: list[str]
    errors: list[str]
    total: int


class DocumentMetadata(BaseModel):
    """Metadati strutturali di un documento."""
    title: Optional[str] = None
    author: Optional[str] = None
    date: Optional[str] = None
    language: Optional[str] = None
    pages: Optional[int] = None


class DocumentSemanticMeta(BaseModel):
    """Metadati semantici estratti."""
    topics: list[str] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)


class DocumentTechMeta(BaseModel):
    """Metadati tecnici."""
    sha256: str
    size_bytes: int
    format: DocumentFormat
    upload_timestamp: str
    mime_type: Optional[str] = None


class DocumentCatalogEntry(BaseModel):
    """Voce nel catalogo documenti."""
    id: str
    filename: str
    format: DocumentFormat
    status: DocumentStatus
    chunks_count: Optional[int] = None
    chunk_strategy: Optional[str] = None
    metadata_structural: Optional[DocumentMetadata] = None
    metadata_semantic: Optional[DocumentSemanticMeta] = None
    metadata_tech: Optional[DocumentTechMeta] = None
    error_message: Optional[str] = None
    updated_at: str
    # Artefatti derivati generati da job secondari (indipendenti dall'indicizzazione)
    wiki_updated_at: Optional[str] = None
    graph_updated_at: Optional[str] = None


class DocumentListResponse(BaseModel):
    """Lista documenti con conteggio."""
    documents: list[DocumentCatalogEntry]
    total: int
    total_chunks: int


# === Attività (cronologia KB) ===

class ActivityAction(str, Enum):
    """Tipologia di modifica tracciata nella cronologia attività."""
    UPLOADED = "uploaded"
    MODIFIED = "modified"
    DELETED = "deleted"
    PARSING = "parsing"
    NORMALIZING = "normalizing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    ERROR = "error"
    REPROCESSING = "reprocessing"
    WIKI_GENERATED = "wiki_generated"
    GRAPH_EXTRACTED = "graph_extracted"


class ActivityEntry(BaseModel):
    """Voce della cronologia attività."""
    id: str
    action: ActivityAction
    doc_id: Optional[str] = None
    filename: str
    timestamp: str
    detail: Optional[str] = None


class ActivityListResponse(BaseModel):
    """Cronologia delle attività recenti."""
    activities: list[ActivityEntry]
    total: int


# === RAG ===

class RAGQuery(BaseModel):
    """Richiesta di interrogazione RAG."""
    question: str = Field(min_length=1, max_length=2000)
    model: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=64, le=4096)
    # Modalità di retrieval: "hybrid" (default) | "dense" | "bm25"
    retrieval_mode: Optional[str] = None


class RAGSource(BaseModel):
    """Fonte citata nella risposta RAG."""
    ref: str  # es. "[1]"
    document_name: str
    location: str  # es. "p. 12, § 3"
    chunk_id: str
    score: float
    snippet: str


class RAGTokenEvent(BaseModel):
    """Evento SSE per singolo token."""
    token: str
    done: bool = False


class RAGSourceEvent(BaseModel):
    """Evento SSE con fonti recuperate."""
    type: str = "sources"
    sources: list[RAGSource]


class RAGMetricsEvent(BaseModel):
    """Evento SSE con metriche della generazione."""
    type: str = "metrics"
    tok_per_sec: float
    ttft: float
    retrieval_time_ms: float


# === Grafo ===

class GraphNode(BaseModel):
    id: str
    label: str
    type: str


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str
    confidence: float = 1.0


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphNodeDetail(BaseModel):
    id: str
    label: str
    type: str
    degree: int
    storytelling: str
    links: list[dict]


# === Wiki ===

class WikiPage(BaseModel):
    id: str
    title: str
    content: str
    sources: list[str]


class WikiIndex(BaseModel):
    groups: list[dict]


# === Modelli LLM ===

class OllamaModelInfo(BaseModel):
    name: str
    size_bytes: Optional[int] = None
    quantization: Optional[str] = None
    family: Optional[str] = None
    active: bool = False


class ModelLoadRequest(BaseModel):
    model: str
    # Opzionale: durata di permanenza in memoria ("30m", "1h", 0 per scaricarla subito)
    keep_alive: Optional[str] = None


class ModelSelectRequest(BaseModel):
    model: str


class CatalogModelInfo(BaseModel):
    """Voce del catalogo dei modelli messi a disposizione dalla piattaforma."""
    name: str
    label: Optional[str] = None
    family: Optional[str] = None
    description: Optional[str] = None
    size_bytes: Optional[int] = None
    quantization: Optional[str] = None
    # Stato rispetto a Ollama
    downloaded: bool = False
    online: bool = False
    active: bool = False


class CatalogStatusResponse(BaseModel):
    """Catalogo completo: stato di Ollama + lista modelli offerti."""
    reachable: bool
    active_model: Optional[str] = None
    keep_alive: Optional[str] = None
    models: list[CatalogModelInfo]


class ModelPullProgress(BaseModel):
    """Avanzamento del download (pull) di un modello."""
    model: str
    status: str = "idle"
    progress: float = 0.0
    message: Optional[str] = None


# === Sistema ===

class SystemMetrics(BaseModel):
    cpu_percent: float
    ram_total_gb: float
    ram_used_gb: float
    ram_percent: float
    vram_total_mb: Optional[float] = None
    vram_used_mb: Optional[float] = None
    ollama_reachable: bool
    chroma_ready: bool
    file_store_ready: bool
    total_documents: int
    total_chunks: int
    active_model: Optional[str] = None


class ServiceStatusResponse(BaseModel):
    ollama: bool
    chromadb: bool
    file_store: bool
    api: bool


# === Admin ===

class AdminConfigUpdate(BaseModel):
    # Strategia di chunking: paragraph | section | sentence | fixed | page
    chunk_strategy: Optional[str] = None
    chunk_size: Optional[int] = Field(default=None, ge=64, le=2048)
    chunk_overlap_pct: Optional[int] = Field(default=None, ge=0, le=50)
    embedding_model: Optional[str] = None
    hnsw_m: Optional[int] = Field(default=None, ge=4, le=64)
    hnsw_ef_construction: Optional[int] = Field(default=None, ge=50, le=500)
    graph_confidence_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    # Grounding delle entità del grafo nel testo dei documenti
    graph_require_grounding: Optional[bool] = None
    graph_max_entity_chars: Optional[int] = Field(default=None, ge=10, le=200)
    metrics_interval_sec: Optional[int] = Field(default=None, ge=1, le=60)
    # --- Retrieval / RAG ---
    rag_top_k_dense: Optional[int] = Field(default=None, ge=1, le=50)
    rag_top_k_keyword: Optional[int] = Field(default=None, ge=1, le=50)
    rag_top_k_final: Optional[int] = Field(default=None, ge=1, le=20)
    rag_rrf_k: Optional[int] = Field(default=None, ge=10, le=200)
    rag_rerank_top_k: Optional[int] = Field(default=None, ge=1, le=100)
    rag_rerank_enabled: Optional[bool] = None
    rag_retrieval_mode: Optional[str] = None
    # Soglia minima di similarità (0-1) per filtrare chunk non pertinenti
    rag_min_similarity_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rag_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    rag_max_tokens: Optional[int] = Field(default=None, ge=64, le=4096)
    # --- Upload ---
    max_upload_size_mb: Optional[int] = Field(default=None, ge=1, le=4096)


# === Ricerca (BE-RF-12/13/14) ===

class SearchMode(str, Enum):
    DENSE = "dense"
    BM25 = "bm25"
    HYBRID = "hybrid"


class SearchQueryRequest(BaseModel):
    """Richiesta di ricerca nella Knowledge Base."""
    query: str = Field(min_length=1, max_length=2000)
    mode: SearchMode = SearchMode.HYBRID
    top_k: int = Field(default=10, ge=1, le=100)
    top_k_dense: Optional[int] = Field(default=None, ge=1, le=100)
    top_k_keyword: Optional[int] = Field(default=None, ge=1, le=100)
    rrf_k: Optional[int] = Field(default=None, ge=10, le=200)
    rerank: Optional[bool] = False
    rerank_top_k: Optional[int] = Field(default=None, ge=1, le=100)


class SearchResultItem(BaseModel):
    id: str
    text: str
    score: float = 0.0
    dense_score: Optional[float] = None
    keyword_score: Optional[float] = None
    rrf_score: Optional[float] = None
    rerank_score: Optional[float] = None
    metadata: dict = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    mode: str
    results: list[SearchResultItem]
    total: int
    latency_ms: float
    rerank_used: bool = False


# === Metadati documento (PATCH, BE-RF-09) ===

class DocumentMetadataUpdate(BaseModel):
    """Aggiornamento dei metadati strutturali/semantici di un documento."""
    title: Optional[str] = None
    author: Optional[str] = None
    date: Optional[str] = None
    language: Optional[str] = None
    pages: Optional[int] = Field(default=None, ge=1)
    topics: Optional[list[str]] = None
    entities: Optional[list[dict]] = None


# === Benchmark (BE-RF-22) ===

class BenchmarkExperiment(str, Enum):
    E1 = "E1"   # Confronto LLM
    E2 = "E2"   # Quantizzazione
    E3 = "E3"   # Originale vs normalizzato
    E4 = "E4"   # BM25 vs Dense vs Hybrid
    E5 = "E5"   # LLM vs RAG
    E6 = "E6"   # KB / Wiki / Graph
    E7 = "E7"   # Scalabilità


class BenchmarkConfig(BaseModel):
    """Configurazione di una run benchmark, salvata per riproducibilità."""
    experiment: BenchmarkExperiment
    label: Optional[str] = None
    # Modelli LLM da valutare (E1/E2/E5). Se assente usa il modello attivo.
    models: Optional[list[str]] = None
    # True per usare la quantizzazione nel confronto E2 (i tag Modello la esprimono).
    top_k: int = Field(default=10, ge=1, le=100)
    top_k_dense: Optional[int] = Field(default=None, ge=1, le=100)
    top_k_keyword: Optional[int] = Field(default=None, ge=1, le=100)
    rrf_k: Optional[int] = Field(default=None, ge=10, le=200)
    rerank: bool = False
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=64, le=4096)
    # Dataset: lista inline di {question, relevant_docs: [doc_id]} oppure
    # nome di un file JSON dentro DATA_DIR/DATASET/benchmark_dataset.json.
    questions: Optional[list[dict]] = None
    dataset_file: Optional[str] = None
    # Limite di domande eseguite (predefinito: tutte).
    limit: Optional[int] = Field(default=None, ge=1, le=1000)


class BenchmarkRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BenchmarkRunSummary(BaseModel):
    run_id: str
    experiment: str
    label: Optional[str]
    status: BenchmarkRunStatus
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    duration_s: Optional[float] = None
    # Breve riepilogo dei risultati (aggregati, se completata).
    summary: Optional[dict] = None


class BenchmarkStartResponse(BaseModel):
    run_id: str
    experiment: str
    status: str
    message: str


# === Job (BE-RF-10) ===

class JobDetail(BaseModel):
    id: str
    type: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_s: Optional[float] = None
    error: Optional[str] = None
    progress: float = 0.0
    result: Optional[dict] = None
    payload: Optional[dict] = None


# === Processing Tracker (FASE 1B) ===

class ProcessingStageResponse(BaseModel):
    """Stato di una singola fase di processing."""
    stage: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    counters: dict = Field(default_factory=dict)


class ConfigurationSnapshotResponse(BaseModel):
    """Snapshot immutabile della configurazione utilizzata da un ProcessingRun."""
    id: str
    document_id: str
    created_at: str
    configuration_hash: str
    sections: dict


class ProcessingRunResponse(BaseModel):
    """Un ProcessingRun con tutte le sue fasi."""
    id: str
    run_type: str
    status: str
    current_stage: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None
    configuration_snapshot: Optional[ConfigurationSnapshotResponse] = None
    stages: dict = Field(default_factory=dict)
    error: Optional[str] = None


class ProcessingDetailResponse(BaseModel):
    """Risposta completa per GET /api/documents/{id}/processing."""
    document_id: str
    current_run: Optional[ProcessingRunResponse] = None
    history: list[ProcessingRunResponse] = Field(default_factory=list)