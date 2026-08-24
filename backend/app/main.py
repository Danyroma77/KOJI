"""
Koji — FastAPI Application Entry Point.
"""

import logging
import traceback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("koji")


def create_app():
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from app.config import settings

    app = FastAPI(
        title="Koji API",
        description="Piattaforma locale di gestione della conoscenza",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Import router uno per uno — se uno fallisce gli altri caricano lo stesso
    routers = [
        ("documents", "app.routers.documents"),
        ("rag", "app.routers.rag"),
        ("graph", "app.routers.graph"),
        ("wiki", "app.routers.wiki"),
        ("models", "app.routers.models_route"),
        ("system", "app.routers.system"),
        ("admin", "app.routers.admin"),
    ]

    for name, module_path in routers:
        try:
            mod = __import__(module_path, fromlist=["router"])
            app.include_router(mod.router, prefix="/api")
            logger.info("Router caricato: %s", name)
        except Exception as e:
            logger.error("Router FALLITO: %s — %s", name, e)
            logger.debug(traceback.format_exc())

    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "service": "koji-api"}

    @app.on_event("startup")
    async def on_startup():
        logger.info("==========================================")
        logger.info("  KOJI — Avvio in corso")
        logger.info("==========================================")
        logger.info("Ollama URL:  %s", settings.OLLAMA_BASE_URL)
        logger.info("Data dir:    %s", settings.DATA_DIR)

        try:
            from app.services.llm_manager import llm_manager
            ok = await llm_manager.check_health()
            if ok:
                logger.info("Ollama:      CONNESSO")
            else:
                logger.warning("Ollama:      non raggiungibile — RAG non disponibile")
        except Exception as e:
            logger.warning("Ollama:      errore verifica — %s", e)

        logger.info("==========================================")
        logger.info("API pronta su http://0.0.0.0:8000")
        logger.info("Docs:  http://localhost:8000/api/docs")
        logger.info("==========================================")

    return app


# Creazione dell'app con gestione crash
try:
    app = create_app()
except Exception as e:
    logger.critical("FATALE all'avvio: %s", e)
    logger.critical(traceback.format_exc())
    # Creiamo un'app minimale così il container non muore
    from fastapi import FastAPI
    app = FastAPI(title="Koji API — ERRORE AVVIO")

    @app.get("/api/health")
    async def health_check():
        return {"status": "error", "message": str(e)}