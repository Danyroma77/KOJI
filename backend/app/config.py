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

    # --- Embedding ---
    EMBEDDING_MODEL: str = Field(default="all-MiniLM-L6-v2")
    EMBEDDING_BATCH_SIZE: int = Field(default=32, ge=1, le=128)
    EMBEDDING_DIMENSION: int = Field(default=384)

    # --- Vector Store ---
    HNSW_M: int = Field(default=16, ge=4, le=64)
    HNSW_EF_CONSTRUCTION: int = Field(default=200, ge=50, le=500)

    # --- RAG ---
    RAG_TOP_K_DENSE: int = Field(default=10, ge=1, le=50)
    RAG_TOP_K_KEYWORD: int = Field(default=10, ge=1, le=50)
    RAG_TOP_K_FINAL: int = Field(default=5, ge=1, le=20)
    RAG_RRF_K: int = Field(default=60)
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

    # --- Knowledge Graph ---
    GRAPH_CONFIDENCE_THRESHOLD: float = Field(default=0.7, ge=0.0, le=1.0)

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
        self.GRAPH_EXTRACTION_MODEL = None

        for d in [self.RAW_DIR, self.PROCESSED_DIR, self.WIKI_DIR,
                  self.EMBEDDING_CACHE_DIR, self.CHROMA_PERSIST_DIR]:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def chunk_overlap_tokens(self) -> int:
        return int(self.CHUNK_SIZE * self.CHUNK_OVERLAP_PCT / 100)


def get_settings() -> Settings:
    return Settings()


settings = get_settings()