"""
Modelli Pydantic per validazione richiesta/risposta.
Ogni router usa questi schemi per garantire coerenza.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


# === Enumerazioni ===

class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    NORMALIZING = "normalizing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    ERROR = "error"


class DocumentFormat(str, Enum):
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
    metadata_structural: Optional[DocumentMetadata] = None
    metadata_semantic: Optional[DocumentSemanticMeta] = None
    metadata_tech: Optional[DocumentTechMeta] = None
    error_message: Optional[str] = None
    updated_at: str


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
    active_model: str


class ServiceStatusResponse(BaseModel):
    ollama: bool
    chromadb: bool
    file_store: bool
    api: bool


# === Admin ===

class AdminConfigUpdate(BaseModel):
    chunk_size: Optional[int] = Field(default=None, ge=64, le=2048)
    chunk_overlap_pct: Optional[int] = Field(default=None, ge=0, le=50)
    embedding_model: Optional[str] = None
    hnsw_m: Optional[int] = Field(default=None, ge=4, le=64)
    hnsw_ef_construction: Optional[int] = Field(default=None, ge=50, le=500)
    graph_confidence_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    metrics_interval_sec: Optional[int] = Field(default=None, ge=1, le=60)