"""
Configurazione centralizzata della piattaforma Koji.
"""

import json
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Configurazione principale della piattaforma."""

    # --- Percorsi ---
    DATA_DIR: Path = Field(default=Path("/data"))
    DATASET_NAME: str = Field(default="default")

    # --- Chunking ---
    CHUNK_SIZE: int = Field(default=512, ge=64, le=2048)
    CHUNK_OVERLAP_PCT: int = Field(default=20, ge=0, le=50)
    # Strategia di segmentazione (selezionabile da Admin, letta a ogni
    # elaborazione):
    #   paragraph — confeziona paragrafi fino alla dimensione target (default)
    #   section   — un chunk per sezione Markdown (titoli H1-H6); le sezioni
    #               oversize vengono rip'zzate ai confini di paragrafo/frase
    #   sentence  — confeziona frasi complete fino alla dimensione target
    #   fixed     — finestra rigida di caratteri con overlap (nessun confine
    #               semantico)
    #   page      — un chunk per pagina del documento originale (solo PDF)
    CHUNK_STRATEGY: str = Field(default="paragraph")

    # --- Embedding ---
    EMBEDDING_MODEL: str = Field(default="all-MiniLM-L6-v2")
    EMBEDDING_BATCH_SIZE: int = Field(default=32, ge=1, le=128)
    EMBEDDING_DIMENSION: int = Field(default=384)
    # Timeout (secondi) della generazione dell'embedding di una query:
    # oltre questo limite la ricerca/RAG fallisce con un errore esplicito
    # invece di lasciare il client in attesa indefinita
    EMBEDDING_TIMEOUT: int = Field(default=30, ge=1, le=600)

    # --- Vector Store ---
    HNSW_M: int = Field(default=16, ge=4, le=64)
    HNSW_EF_CONSTRUCTION: int = Field(default=200, ge=50, le=500)

    # --- RAG ---
    RAG_TOP_K_DENSE: int = Field(default=10, ge=1, le=50)
    RAG_TOP_K_KEYWORD: int = Field(default=10, ge=1, le=50)
    RAG_TOP_K_FINAL: int = Field(default=5, ge=1, le=20)
    RAG_RRF_K: int = Field(default=60, ge=10, le=200)
    # Numero di candidati su cui applicare il cross-encoder di re-ranking.
    RAG_RERANK_TOP_K: int = Field(default=20, ge=1, le=100)
    # Timeout (secondi) del re-ranking con cross-encoder: oltre questo limite
    # si prosegue con l'ordinamento del retriever (fallback offline)
    RAG_RERANK_TIMEOUT: int = Field(default=20, ge=1, le=300)
    # Abilita/disabilita il re-ranking con cross-encoder (BE-RF-15: "se configurato").
    RAG_RERANK_ENABLED: bool = Field(default=True)
    # Modalità di retrieval di default per RAG e ricerca: "hybrid" | "dense" | "bm25".
    RAG_RETRIEVAL_MODE: str = Field(default="hybrid")
    RAG_TEMPERATURE: float = Field(default=0.3, ge=0.0, le=2.0)
    RAG_MAX_TOKENS: int = Field(default=1024, ge=64, le=4096)

    # --- LLM (Ollama in Docker) ---
    OLLAMA_BASE_URL: str = Field(default="http://ollama:11434")
    OLLAMA_MODEL: str = Field(default="phi3:3.8b")
    OLLAMA_TIMEOUT: int = Field(default=120)
    # Quanto tenere un modello in memoria dopo una richiesta ("metterlo in linea")
    OLLAMA_KEEP_ALIVE: str = Field(default="30m")
    # Timeout per il download (pull) dei modelli — alcuni sono da multi-GB
    OLLAMA_PULL_TIMEOUT: int = Field(default=7200, ge=60)
    # Catalogo dei modelli messi a disposizione nella pagina Modelli.
    # Modelli scelti: Meta Llama 3.2, Mistral 7B, Alibaba Qwen 2.5,
    # Google Gemma 2, Microsoft Phi-3 — tutti in quantizzazione Q4_K_M
    # (configurazione hardware). Da env KOJI_AVAILABLE_MODELS si passa una
    # lista JSON, es. '["llama3.2:3b","phi3:3.8b"]'
    AVAILABLE_MODELS: list[str] = Field(default=[
        "llama3.2:3b",
        "mistral:7b",
        "qwen2.5:3b",
        "gemma2:2b",
        "phi3:3.8b",
    ])

    @field_validator("AVAILABLE_MODELS", mode="before")
    @classmethod
    def parse_available_models(cls, value):
        """Accetta una lista Python oppure una stringa JSON già decodificata."""
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
        """Normalizza la strategia di chunking (alias italiani ammessi)."""
        if not isinstance(value, str) or not value.strip():
            return "paragraph"
        aliases = {
            "paragraph": "paragraph", "paragrafo": "paragraph", "paragrafi": "paragraph",
            "section": "section", "sezione": "section", "sezioni": "section",
            "heading": "section", "markdown": "section",
            "sentence": "sentence", "frase": "sentence", "frasi": "sentence",
            "fixed": "fixed", "fisso": "fixed", "finestra": "fixed",
            "window": "fixed", "raw": "fixed",
            "page": "page", "pagina": "page", "pagine": "page",
        }
        return aliases.get(value.strip().lower(), "paragraph")

    @field_validator("RAG_RETRIEVAL_MODE", mode="before")
    @classmethod
    def parse_retrieval_mode(cls, value):
        """Normalizza la modalità di retrieval: accetta anche valori estesi."""
        if isinstance(value, str):
            v = value.strip().lower().replace("-", "").replace("_", "")
            aliases = {"hybrid": "hybrid", "bm25": "bm25", "bm25keyword": "bm25",
                       "keyword": "bm25", "dense": "dense", "vector": "dense"}
            return aliases.get(v, "hybrid")
        return "hybrid"

    # --- Upload documenti ---
    MAX_UPLOAD_SIZE_MB: int = Field(default=200, ge=1, le=4096)

    # --- Knowledge Graph ---
    GRAPH_CONFIDENCE_THRESHOLD: float = Field(default=0.7, ge=0.0, le=1.0)
    # Le entità devono essere citate testualmente nel documento: le triple
    # prodotte dal LLM che non compaiono verbatim nel testo vengono scartate
    # (nessuna entità "inventata": il grafo è generato a runtime dai contenuti).
    GRAPH_REQUIRE_GROUNDING: bool = True
    # Lunghezza massima dell'etichetta di un'entità (frasi intere = rumore).
    GRAPH_MAX_ENTITY_CHARS: int = Field(default=60, ge=10, le=200)

    # --- Monitoraggio ---
    METRICS_INTERVAL_SEC: int = Field(default=5, ge=1, le=60)

    # --- Server ---
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    CORS_ORIGINS: list[str] = Field(default=["http://localhost:3000"])

    # <<< QUESTA RIGA È LA CHIAVE >>>
    model_config = {"env_prefix": "KOJI_", "extra": "allow"}

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
        # Benchmark: risultati persistenti delle run sperimentali (BE-RF-22).
        self.BENCHMARKS_DIR = dataset_path / "benchmarks"
        # Dataset di domande + ground truth per i benchmark che ne richiedono.
        self.BENCHMARK_DATASET_FILE = dataset_path / "benchmark_dataset.json"
        self.GRAPH_EXTRACTION_MODEL = None

        for d in [self.RAW_DIR, self.PROCESSED_DIR, self.WIKI_DIR,
                  self.EMBEDDING_CACHE_DIR, self.CHROMA_PERSIST_DIR,
                  self.BENCHMARKS_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def chunk_overlap_tokens(self) -> int:
        return int(self.CHUNK_SIZE * self.CHUNK_OVERLAP_PCT / 100)


def get_settings() -> Settings:
    return Settings()


settings = get_settings()