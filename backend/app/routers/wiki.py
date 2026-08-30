"""
Router Wiki — Endpoint per la Wiki semantica.
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException

from app.models import WikiPage, WikiIndex
from app.services.wiki_generator import wiki_generator

router = APIRouter(prefix="/wiki", tags=["wiki"])


@router.get("/index", response_model=WikiIndex)
async def get_wiki_index():
    """Restituisce la struttura dell'indice wiki."""
    return WikiIndex(**wiki_generator.get_index())


@router.post("/rebuild")
async def rebuild_wiki():
    """Rigenera la wiki da tutti i documenti pronti (operazione asincrona).

    L'operazione viene eseguita in background come job per non bloccare
    l'API; lo stato è consultabile via /api/jobs/{job_id}.
    """
    from app.services.job_queue import job_queue
    from app.routers.documents import _load_catalog

    catalog = _load_catalog()
    job = job_queue.enqueue("generate_wiki", {
        "doc_id": None,
        "filename": "KB",
    })
    return {
        "status": "ok",
        "job_id": job.id,
        "message": f"Rigenerazione wiki accodata ({len(catalog.get('documents', []))} documenti in catalogo)",
    }


@router.get("/page/{page_id}", response_model=WikiPage)
async def get_wiki_page(page_id: str):
    """Restituisce il contenuto di una pagina wiki."""
    page = wiki_generator.get_page(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"Pagina wiki '{page_id}' non trovata")
    return WikiPage(**page)