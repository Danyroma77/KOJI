"""
=============================================================================
MONITOR — RACCOLTA METRICHE DI SISTEMA TRAMITE PSUTIL
=============================================================================

Raccoglie metriche di sistema per il monitoraggio della piattaforma.
Include CPU, RAM, VRAM (NVIDIA), stato servizi e statistiche KB.

METRICHE RACCOLTE:
- CPU: percentuale di utilizzo
- RAM: totale, usata, percentuale
- VRAM: totale, usata (se GPU NVIDIA disponibile)
- Servizi: Ollama, ChromaDB, File Store
- KB: numero documenti, numero chunk

STRUMENTI:
- psutil: metriche CPU/RAM
- nvidia-smi: metriche GPU (opzionale)
- API Ollama: stato connettività
"""

from __future__ import annotations
import psutil
from app.services.llm_manager import llm_manager
from app.services.vector_store import vector_store
from app.config import settings


async def get_system_metrics() -> dict:
    """
    Raccolta completa delle metriche di sistema.
    
    Returns:
        Dict con metriche CPU, RAM, VRAM, servizi e KB
        
    Note:
        - VRAM disponibile solo con GPU NVIDIA e nvidia-smi installato
        - Il modello attivo è riportato solo se effettivamente installato
    """
    # Risorse hardware
    cpu_percent = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    ram_total_gb = round(ram.total / (1024 ** 3), 1)
    ram_used_gb = round(ram.used / (1024 ** 3), 1)
    ram_percent = ram.percent

    # VRAM (se disponibile via nvidia-smi o AMD)
    vram_total_mb = None
    vram_used_mb = None
    try:
        result = await _run_nvidia_smi()
        if result:
            vram_total_mb = result.get("total_mb")
            vram_used_mb = result.get("used_mb")
    except Exception:
        pass

    # Stato servizi
    ollama_ok = await llm_manager.check_health()

    # Modello attivo SOLO se è davvero installato in Ollama.
    # Il default di config (phi3:3.8b) da solo non basta: senza modello
    # scaricato non esiste un LLM realmente "attivo".
    active_model = None
    if ollama_ok:
        want = llm_manager.active_model
        installed = await llm_manager.installed_names()
        want_base = (want or "").split(":", 1)[0].lower()
        installed_bases = {n.split(":", 1)[0].lower() for n in installed}
        if want in installed or want_base in installed_bases:
            active_model = want

    chroma_ok = True
    try:
        vector_store.initialize()
        _ = vector_store.count
    except Exception:
        chroma_ok = False

    file_store_ok = settings.DATA_DIR.exists()

    # Statistiche KB
    try:
        vs_stats = vector_store.get_stats()
        total_chunks = vs_stats["total_chunks"]
    except Exception:
        total_chunks = 0

    # Conta documenti dal catalogo
    total_docs = 0
    catalog_file = settings.CATALOG_FILE
    if catalog_file.exists():
        import json
        catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
        total_docs = len(catalog.get("documents", []))

    return {
        "cpu_percent": cpu_percent,
        "ram_total_gb": ram_total_gb,
        "ram_used_gb": ram_used_gb,
        "ram_percent": ram_percent,
        "vram_total_mb": vram_total_mb,
        "vram_used_mb": vram_used_mb,
        "ollama_reachable": ollama_ok,
        "chroma_ready": chroma_ok,
        "file_store_ready": file_store_ok,
        "total_documents": total_docs,
        "total_chunks": total_chunks,
        "active_model": active_model,
    }


async def get_service_status() -> dict:
    """
    Stato semplificato dei servizi.
    
    Returns:
        Dict con stato di Ollama, ChromaDB, File Store e API
    """
    ollama_ok = await llm_manager.check_health()

    chroma_ok = True
    try:
        vector_store.initialize()
        _ = vector_store.count
    except Exception:
        chroma_ok = False

    return {
        "ollama": ollama_ok,
        "chromadb": chroma_ok,
        "file_store": settings.DATA_DIR.exists(),
        "api": True,
    }


async def _run_nvidia_smi() -> dict | None:
    """
    Esegue nvidia-smi per ottenere info VRAM.
    
    Returns:
        Dict con total_mb e used_mb, o None se non disponibile
    """
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            return {
                "total_mb": float(parts[0]),
                "used_mb": float(parts[1]),
            }
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None