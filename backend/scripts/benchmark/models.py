# backend/scripts/benchmark/models.py
from sentence_transformers import SentenceTransformer
from typing import Dict, Any
import json

MODEL_REGISTRY = {
    "sentence-transformers/all-MiniLM-L6-v2": {
        "id": "sentence-transformers/all-MiniLM-L6-v2",
        "revision": "master",
        "embedding_dim": 384,
        "max_length": 256,
    },
    "sentence-transformers/longformer-base-4096": {
        "id": "sentence-transformers/longformer-base-4096",
        "revision": "master",
        "embedding_dim": 768,
        "max_length": 4096,
    },
    "nomic-ai/nomic-embed-text-v1.5": {
        "id": "nomic-ai/nomic-embed-text-v1.5",
        "revision": "main",
        "embedding_dim": 768,
        "max_length": 8192,
    },
}

def load_model(model_id: str) -> SentenceTransformer:
    model = SentenceTransformer(model_id)
    return model

def get_model_info(model: SentenceTransformer, model_id: str) -> Dict[str, Any]:
    info = {}
    info["model_id"] = model_id
    info["embedding_dim"] = model.get_sentence_embedding_dimension()
    info["max_length"] = getattr(model, "max_seq_length", MODEL_REGISTRY[model_id]["max_length"])
    info["tokenizer_type"] = type(model.tokenizer).__name__
    return info
