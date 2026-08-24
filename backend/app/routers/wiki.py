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


@router.get("/page/{page_id}", response_model=WikiPage)
async def get_wiki_page(page_id: str):
    """Restituisce il contenuto di una pagina wiki."""
    page = wiki_generator.get_page(page_id)
    if not page:
        raise HTTPException(status_code=404, detail=f"Pagina wiki '{page_id}' non trovata")
    return WikiPage(**page)