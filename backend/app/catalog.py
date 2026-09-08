"""
=============================================================================
CATALOGO DEI MODELLI LLM
=============================================================================

Questo modulo contiene i metadati dei modelli LLM messi a disposizione 
dalla piattaforma Koji. Questi dati sono usati dalla pagina "Modelli" 
del frontend per mostrare le opzioni disponibili anche prima che i modelli 
vengano scaricati da Ollama.

STRUTTURA DEI METADATI:
- label: nome visualizzato nell'interfaccia
- family: famiglia del modello (es. "Meta Llama 3.2")
- description: descrizione delle caratteristiche
- size_bytes: dimensione stimata del file modello
- quantization: tipo di quantizzazione (Q4_K_M è un buon compromesso qualità/dimensione)

NOTE:
- Le dimensioni sono stimate per la quantizzazione Q4_K_M
- Quando un modello è installato, Ollama fornisce i dati reali che sovrascrivono queste stime
- I modelli sono scelti per coprire diversi casi d'uso: leggeri (2B-3B) per hardware limitato, più grandi (7B) per qualità superiore
"""

from __future__ import annotations

# Catalogo dei modelli con metadati leggeri
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
    """
    Recupera i metadati di un modello dal catalogo.
    
    Args:
        name: Nome del modello (es. "phi3:3.8b")
        
    Returns:
        Dict con i metadati del modello, o dict vuoto se non presente.
        Restituisce una copia per evitare modifiche accidentali al catalogo.
    """
    return dict(MODEL_CATALOG.get(name, {}) or {})