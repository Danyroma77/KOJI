"""
Router Modelli — Gestione modelli LLM tramite Ollama.
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query

from app.catalog import get_model_metadata
from app.config import settings
from app.models import (
    CatalogModelInfo,
    CatalogStatusResponse,
    ModelLoadRequest,
    ModelPullProgress,
    ModelSelectRequest,
    OllamaModelInfo,
)
from app.services.llm_manager import llm_manager

router = APIRouter(prefix="/models", tags=["models"])


def _base_name(name: str) -> str:
    """Riduce un nome modello alla parte base (senza tag)."""
    return (name or "").split(":", 1)[0].lower()


def _find_installed(installed: dict, raw_name: str):
    """Cerca un modello tra quelli installati: prima uguaglianza esatta, poi base."""
    if raw_name in installed:
        return installed[raw_name]
    base = _base_name(raw_name)
    for name, meta in installed.items():
        if _base_name(name) == base:
            return meta
    return None


@router.get("/catalog")
async def model_catalog() -> CatalogStatusResponse:
    """Catalogo dei modelli messi a disposizione dalla piattaforma.

    Per ogni modello del catalogo riporta lo stato reale rispetto a Ollama:
    se è stato scaricato (downloaded), se è caricato in memoria / 'in linea'
    (online) e se è il modello attivo per la generazione RAG.
    """
    installed = {}
    running_exact: set[str] = set()
    running_bases: set[str] = set()
    reachable = True

    try:
        tags = await llm_manager.list_models()
        installed = {m.get("name", ""): m for m in tags if m.get("name")}
    except Exception:
        reachable = False

    if reachable:
        try:
            ps = await llm_manager.running_models()
            running_exact = {m.get("name", "") for m in ps if m.get("name")}
            running_bases = {_base_name(n) for n in running_exact}
        except Exception:
            pass  # /api/ps non disponibile: online resta False

    active = llm_manager.active_model or settings.OLLAMA_MODEL
    active_base = _base_name(active)

    models_out: list[CatalogModelInfo] = []
    for raw_name in settings.AVAILABLE_MODELS:
        meta = get_model_metadata(raw_name)
        inst = _find_installed(installed, raw_name)
        downloaded = inst is not None
        online = (
            downloaded
            and (raw_name in running_exact or _base_name(raw_name) in running_bases)
        )
        # Un modello può essere "attivo" solo se è stato davvero scaricato:
        # il default di configurazione da solo non basta, altrimenti Phi-3
        # (mai scaricato) risulterebbe attivo pur non esistendo in Ollama.
        is_active = downloaded and (
            raw_name == active or _base_name(raw_name) == active_base
        )

        details = (inst or {}).get("details", {}) if downloaded else {}
        size_bytes = (inst or {}).get("size") if downloaded else meta.get("size_bytes")

        models_out.append(
            CatalogModelInfo(
                name=raw_name,
                label=meta.get("label") or raw_name,
                family=meta.get("family") or details.get("family"),
                description=meta.get("description"),
                size_bytes=size_bytes,
                quantization=(
                    details.get("quantization_level")
                    if details.get("quantization_level")
                    else meta.get("quantization")
                ),
                downloaded=downloaded,
                online=online,
                active=is_active,
            )
        )

    return CatalogStatusResponse(
        reachable=reachable,
        active_model=next((m.name for m in models_out if m.active), None),
        keep_alive=settings.OLLAMA_KEEP_ALIVE,
        models=models_out,
    )


@router.get("/active")
async def get_active_model():
    """Restituisce il modello LLM attualmente attivo.

    Ritorna None se il modello configurato/selezionato non è ancora
    stato scaricato in Ollama.
    """
    want = llm_manager.active_model
    installed = await llm_manager.installed_names()
    if want in installed:
        return {"model": want}
    want_base = _base_name(want)
    if any(_base_name(n) == want_base for n in installed):
        return {"model": want}
    return {"model": None}


@router.post("/select")
async def select_model(request: ModelSelectRequest):
    """Seleziona il modello attivo per la generazione RAG.

    Consente la selezione solo se il modello è già stato scaricato.
    """
    installed = await llm_manager.installed_names()
    ok = request.model in installed or any(
        _base_name(n) == _base_name(request.model) for n in installed
    )
    if not ok:
        raise HTTPException(
            status_code=400,
            detail=f"Modello {request.model} non scaricato: impossibile selezionarlo",
        )
    llm_manager.set_active_model(request.model)
    return {"status": "ok", "active_model": llm_manager.active_model}


@router.get("")
async def list_models() -> list[OllamaModelInfo]:
    """Lista dei modelli scaricati in Ollama (per la selezione in RAG).

    Ritorna SOLO i modelli già scaricati e segnala con `active` quale è
    attualmente attivo (ce ne può essere al massimo uno).
    """
    try:
        models = await llm_manager.list_models()
        return [
            OllamaModelInfo(
                name=m.get("name", ""),
                size_bytes=m.get("size"),
                quantization=m.get("details", {}).get("quantization_level"),
                family=m.get("details", {}).get("family"),
                active=llm_manager.is_active(m.get("name", "")),
            )
            for m in models
        ]
    except Exception:
        return []


@router.post("/pull")
async def pull_model(request: ModelSelectRequest):
    """Avvia il download (pull) di un modello dal registry Ollama.

    Il download prosegue in background; lo stato è leggibile via
    GET /api/models/pull/progress?model=...
    """
    try:
        result = await llm_manager.pull_model(request.model)
        return {"status": result.get("status"), "model": request.model}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pull/progress", response_model=ModelPullProgress)
async def model_pull_progress(
    model: str = Query(..., description="Nome del modello in download"),
) -> ModelPullProgress:
    """Avanzamento del download (pull) di un modello."""
    state = llm_manager.pull_status(model)
    return ModelPullProgress(
        model=state.get("model", model),
        status=state.get("status", "idle"),
        progress=state.get("progress", 0.0),
        message=state.get("message"),
    )


@router.post("/load")
async def load_model(request: ModelLoadRequest):
    """Carica un modello nella memoria di Ollama ('metterlo in linea')."""
    try:
        await llm_manager.load_model(request.model, request.keep_alive)
        return {"status": "ok", "model": request.model, "action": "load"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/unload")
async def unload_model(request: ModelSelectRequest):
    """Libera la memoria scaricando il modello, togliendolo dalla linea."""
    try:
        await llm_manager.unload_model(request.model)
        return {"status": "ok", "model": request.model, "action": "unload"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/health")
async def ollama_health():
    """Verifica che Ollama sia raggiungibile."""
    ok = await llm_manager.check_health()
    return {"reachable": ok}