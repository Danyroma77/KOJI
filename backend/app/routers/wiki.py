"""
=============================================================================
ROUTER WIKI — ENDPOINT PER LA WIKI SEMANTICA
=============================================================================

Questo router espone endpoint per consultare e rigenerare la Wiki semantica,
una rappresentazione navigabile dei contenuti della Knowledge Base.

ENDPOINT:
GET  /api/wiki/index         — Indice della wiki (struttura a gruppi)
POST /api/wiki/rebuild       — Rigenera wiki da documenti (job in background)
GET  /api/wiki/page/{id}     — Contenuto di una pagina wiki

STRUTTURA WIKI:
- Indice: gruppi di pagine (Regolamenti, Circolari, Procedure, FAQ, Altro)
- Pagine: contenuto Markdown con fonti e riferimenti
- Generazione: aggregazione automatica da sezioni dei documenti

GENERAZIONE:
- Le pagine sono generate dalle sezioni dei documenti processati
- Il LLM può migliorare/introdurre le pagine (se disponibile)
- L'indice è costruito automaticamente dai nomi dei file
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException

from app.models import WikiPage, WikiIndex
from app.services.wiki_generator import wiki_generator

# Router con prefisso /api/wiki
router = APIRouter(prefix="/wiki", tags=["wiki"])


@router.get("/index", response_model=WikiIndex)
async def get_wiki_index():
    """
    Restituisce la struttura dell'indice wiki.
    
    Returns:
        WikiIndex con gruppi di pagine (Regolamenti, Circolare, etc.)
    """
    return WikiIndex(**wiki_generator.get_index())


@router.post("/rebuild")
async def rebuild_wiki():
    """
    Rigenera la wiki da tutti i documenti pronti.
    
    Returns:
        Job ID per monitorare l'avanzamento
        
    Note:
        - L'operazione è asincrona (job in background)
        - Lo stato è consultabile via GET /api/jobs/{job_id}
        - La wiki aggrega sezioni da tutti i documenti pronti
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
    """
    Restituisce il contenuto di una pagina wiki.
    
    Args:
        page_id: Identificativo della pagina (slug)
        
    Returns:
        WikiPage con titolo, contenuto Markdown e fonti
        
    Raises:
        404: Se la pagina non esiste
    """
    page = wiki_generator.get_page(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"Pagina wiki '{page_id}' non trovata")
    return WikiPage(**page)