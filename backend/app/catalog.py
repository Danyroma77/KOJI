"""
Catalogo dei modelli messi a disposizione dalla piattaforma.

Contiene solo metadati *leggeri* (label, famiglia, descrizione, dimensione
stimata) usati dalla pagina Modelli per mostrare i modelli offerti anche
prima che vengano scaricati da Ollama. Quando il modello è già installato
la dimensione/quantizzazione reali provengono da Ollama e sovrascrivono
queste stime.
"""

from __future__ import annotations

MODEL_CATALOG: dict[str, dict] = {
    "phi3:3.8b": {
        "label": "Phi-3 Mini (3.8B)",
        "family": "Microsoft Phi-3",
        "description": "Modello compatto e veloce, buon compromesso per RAG su hardware limitato.",
        "size_bytes": 2_321_839_104,  # ~2.2 GB Q4_K_M
        "quantization": "Q4_K_M",
    },
    "gemma2:2b": {
        "label": "Gemma 2 (2B)",
        "family": "Google Gemma 2",
        "description": "Molto leggero, adatto a dispositivi con poca memoria.",
        "size_bytes": 1_677_721_600,  # ~1.6 GB Q4_K_M
        "quantization": "Q4_K_M",
    },
    "llama3.2:3b": {
        "label": "Llama 3.2 (3B)",
        "family": "Meta Llama 3.2",
        "description": "Generalista di nuova generazione, equilibrato per RAG.",
        "size_bytes": 2_013_265_920,  # ~1.9 GB Q4_K_M
        "quantization": "Q4_K_M",
    },
    "qwen2.5:3b": {
        "label": "Qwen 2.5 (3B)",
        "family": "Alibaba Qwen 2.5",
        "description": "Buon supporto multilingua ed istruzioni strutturate.",
        "size_bytes": 1_989_668_864,  # ~1.9 GB Q4_K_M
        "quantization": "Q4_K_M",
    },
    "mistral:7b": {
        "label": "Mistral (7B)",
        "family": "Mistral AI",
        "description": "Più capiente e capace, richiede più memoria VRAM/RAM.",
        "size_bytes": 4_722_032_640,  # ~4.4 GB Q4_K_M
        "quantization": "Q4_K_M",
    },
}


def get_model_metadata(name: str) -> dict:
    """Ritorna i metadati del modello se presenti nel catalogo, altrimenti un dict vuoto."""
    return dict(MODEL_CATALOG.get(name, {}) or {})