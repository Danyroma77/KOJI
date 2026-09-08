"""
=============================================================================
CONFIGURAZIONE CENTRALIZZATA DELLA PIATTAFORMA KOJI
=============================================================================

Questo modulo definisce tutta la configurazione della piattaforma Koji.
Le impostazioni possono essere sovrascritte tramite variabili d'ambiente 
con prefisso KOJI_ (es. KOJI_CHUNK_SIZE=1024).

Vedi la docstring della classe Settings per i dettagli di ogni sezione.
"""

import json
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """
    Classe principale di configurazione.
    
    Utilizza pydantic-settings per validazione automatica e caricamento da
    variabili d'ambiente. I field validator permettono di normalizzare i
    valori in ingresso (es. alias per le strategie di chunking).
    """

    # =========================================================================
    # PERCORSI FILESYSTEM
    # =========================================================================
    # DATA_DIR: directory base per tutti i dati (default: /data in Docker)
    # DATASET_NAME: nome del dataset corrente (permette multi-dataset)
    DATA_DIR: Path = Field(default=Path("/data"))
    DATASET_NAME: str = Field(default="default")

    # =========================================================================
    # CONFIGURAZIONE CHUNKING
    # =========================================================================
    # Il chunking suddivide i documenti in segmenti per l'indicizzazione.
    # CHUNK_SIZE: dimensione target in token (1 token ≈ 4 caratteri italiani)
    # CHUNK_OVERLAP_PCT: percentuale di sovrapposizione tra chunk consecutivi
    CHUNK_SIZE: int = Field(default=512, ge=64, le=2048)
    CHUNK_OVERLAP_PCT: int = Field(default=20, ge=0, le=50)
    
    # Strategia di segmentazione (selezionabile da Admin, letta a ogni elaborazione):
    #   paragraph — confeziona paragrafi fino alla dimensione target (default)
    #   section   — un chunk per sezione Markdown (titoli H1-H6)
    #   sentence  — confeziona frasi complete fino alla dimensione target
    #   fixed     — finestra rigida di caratteri con overlap (nessun confine semantico)
    #   page      — un chunk per pagina del documento originale (solo PDF)
    CHUNK_STRATEGY: str = Field(default="paragraph")

    # =========================================================================
    # CONFIGURAZIONE EMBEDDING
    # =========================================================================
    # Gli embedding sono vettori numerici che rappresentano il significato semantico.
    # Il modello all-MiniLM-L6-v2 è leggero (80MB), adatto per hardware limitato.
    EMBEDDING_MODEL: str = Field(default="all-MiniLM-L6-v2")
    EMBEDDING_BATCH_SIZE: int = Field(default=32, ge=1, le=128)
    EMBEDDING_DIMENSION: int = Field(default=384)
    
    # Timeout (secondi) per l'embedding di una query: oltre questo limite
    # la ricerca/RAG fallisce con un errore esplicito (no attesa indefinita)
    EMBEDDING_TIMEOUT: int = Field(default=30, ge=1, le=600)

    # =========================================================================
    # CONFIGURAZIONE VECTOR STORE (ChromaDB con HNSW)
    # =========================================================================
    # HNSW (Hierarchical Navigable Small World): indice per ricerca approssimativa
    # HNSW_M: numero di connessioni per nodo (maggiore = più preciso, più lento)
    # HNSW_EF_CONSTRUCTION: fattore di espansione in costruzione (qualità indice)
    HNSW_M: int = Field(default=16, ge=4, le=64)
    HNSW_EF_CONSTRUCTION: int = Field(default=200, ge=50, le=500)

    # =========================================================================
    # CONFIGURAZIONE RAG (Retrieval-Augmented Generation)
    # =========================================================================
    # Parametri di retrieval
    RAG_TOP_K_DENSE: int = Field(default=10, ge=1, le=50)      # Risultati ricerca vettoriale
    RAG_TOP_K_KEYWORD: int = Field(default=10, ge=1, le=50)    # Risultati ricerca BM25
    RAG_TOP_K_FINAL: int = Field(default=5, ge=1, le=20)       # Chunk finali nel contesto LLM
    RAG_RRF_K: int = Field(default=60, ge=10, le=200)          # Parametro RRF per fusione
    
    # Re-ranking con cross-encoder (BE-RF-15): migliora la pertinenza dei risultati
    RAG_RERANK_TOP_K: int = Field(default=20, ge=1, le=100)    # Candidati da riordinare
    RAG_RERANK_TIMEOUT: int = Field(default=20, ge=1, le=300)  # Timeout re-ranking
    RAG_RERANK_ENABLED: bool = Field(default=True)             # Abilita/disabilita
    
    # Modalità di retrieval: "hybrid" (denso+BM25), "dense" (solo vettoriale), "bm25" (solo keyword)
    RAG_RETRIEVAL_MODE: str = Field(default="hybrid")
    
    # Soglia minima di similarità (0-1) per filtrare chunk non pertinenti
    RAG_MIN_SIMILARITY_THRESHOLD: float = Field(default=0.0, ge=0.0, le=1.0)
    
    # Parametri di generazione LLM
    RAG_TEMPERATURE: float = Field(default=0.3, ge=0.0, le=2.0)  # Creatività (0 = deterministico)
    RAG_MAX_TOKENS: int = Field(default=1024, ge=64, le=4096)    # Lunghezza massima risposta

    # =========================================================================
    # CONFIGURAZIONE LLM (Ollama in Docker)
    # =========================================================================
    # Ollama esegue i modelli LLM localmente via HTTP sulla porta 11434
    OLLAMA_BASE_URL: str = Field(default="http://ollama:11434")
    OLLAMA_MODEL: str = Field(default="phi3:3.8b")  # Modello di default
    OLLAMA_TIMEOUT: int = Field(default=300)        # Timeout generazione (5 min)
    
    # Durata mantenimento modello in memoria dopo una richiesta
    OLLAMA_KEEP_ALIVE: str = Field(default="30m")
    
    # Timeout per il download (pull) dei modelli (alcuni sono multi-GB)
    OLLAMA_PULL_TIMEOUT: int = Field(default=7200, ge=60)
    
    # Catalogo modelli disponibili (quantizzazione Q4_K_M per hardware consumer)
    # Override da env: KOJI_AVAILABLE_MODELS='["llama3.2:3b","phi3:3.8b"]'
    AVAILABLE_MODELS: list[str] = Field(default=[
        "llama3.2:3b",
        "mistral:7b",
        "qwen2.5:3b",
        "gemma2:2b",
        "phi3:3.8b",
    ])

    # =========================================================================
    # FIELD VALIDATOR - Normalizzano i valori in ingresso
    # =========================================================================
    
    @field_validator("AVAILABLE_MODELS", mode="before")
    @classmethod
    def parse_available_models(cls, value):
        """Accetta una lista Python oppure una stringa JSON da env var."""
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return [str(m).strip() for m in parsed if str(m).strip()]
                except (ValueError, TypeError):
                    pass
            return [m.strip() for m in text.split(",") if m.strip()]
        return value

    @field_validator("CHUNK_STRATEGY", mode="before")
    @classmethod
    def parse_chunk_strategy(cls, value):
        """Normalizza la strategia di chunking (accetta alias italiani)."""
        if not isinstance(value, str) or not value.strip():
            return "paragraph"
        aliases = {
            "paragraph": "paragraph", "paragrafo": "paragraph",
            "section": "section", "sezione": "section",
            "sentence": "sentence", "frase": "sentence",
            "fixed": "fixed", "fisso": "fixed",
            "page": "page", "pagina": "page",
        }
        return aliases.get(value.strip().lower(), "paragraph")

    @field_validator("RAG_RETRIEVAL_MODE", mode="before")
    @classmethod
    def parse_retrieval_mode(cls, value):
        """Normalizza la modalità di retrieval (accetta sinonimi)."""
        if isinstance(value, str):
            v = value.strip().lower().replace("-", "").replace("_", "")
            aliases = {"hybrid": "hybrid", "bm25": "bm25", "keyword": "bm25",
                       "dense": "dense", "vector": "dense"}
            return aliases.get(v, "hybrid")
        return "hybrid"

    # =========================================================================
    # CONFIGURAZIONI AGGIUNTIVE
    # =========================================================================
    MAX_UPLOAD_SIZE_MB: int = Field(default=200, ge=1, le=4096)
    
    # Knowledge Graph
    GRAPH_CONFIDENCE_THRESHOLD: float = Field(default=0.7, ge=0.0, le=1.0)
    GRAPH_REQUIRE_GROUNDING: bool = True  # Entità devono essere nel testo
    GRAPH_MAX_ENTITY_CHARS: int = Field(default=60, ge=10, le=200)
    
    # Monitoraggio
    METRICS_INTERVAL_SEC: int = Field(default=5, ge=1, le=60)
    
    # Server
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    CORS_ORIGINS: list[str] = Field(default=["http://localhost:3000"])

    # Prefisso KOJI_ per variabili d'ambiente
    model_config = {"env_prefix": "KOJI_", "extra": "allow"}

    # =========================================================================
    # INIZIALIZZAZIONE PERCORSI
    # =========================================================================
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        dataset_path = self.DATA_DIR / self.DATASET_NAME
        self.RAW_DIR = dataset_path / "raw"
        self.PROCESSED_DIR = dataset_path / "processed"
        self.WIKI_DIR = dataset_path / "wiki"
        self.GRAPH_FILE = dataset_path / "graph.json"
        self.CATALOG_FILE = dataset_path / "catalog.json"
        self.ACTIVITY_LOG_FILE = dataset_path / "activities.json"
        self.EMBEDDING_CACHE_DIR = dataset_path / "embedding_cache"
        self.CHROMA_PERSIST_DIR = dataset_path / "chroma"
        self.BENCHMARKS_DIR = dataset_path / "benchmarks"
        self.BENCHMARK_DATASET_FILE = dataset_path / "benchmark_dataset.json"
        self.GRAPH_EXTRACTION_MODEL = None

        # Creazione automatica directory
        for d in [self.RAW_DIR, self.PROCESSED_DIR, self.WIKI_DIR,
                  self.EMBEDDING_CACHE_DIR, self.CHROMA_PERSIST_DIR,
                  self.BENCHMARKS_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def chunk_overlap_tokens(self) -> int:
        """Calcola l'overlap in token dalla percentuale configurata."""
        return int(self.CHUNK_SIZE * self.CHUNK_OVERLAP_PCT / 100)


def get_settings() -> Settings:
    """Factory per ottenere l'istanza singleton delle impostazioni."""
    return Settings()


# Istanza globale usata in tutto il backend
settings = get_settings()