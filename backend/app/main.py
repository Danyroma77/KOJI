"""
=============================================================================
KOJI — FastAPI Application Entry Point
=============================================================================

Questo modulo è il punto di ingresso principale dell'applicazione Koji, una 
piattaforma locale di gestione della conoscenza basata su RAG (Retrieval-
Augmented Generation).

ARCHITETTURA:
- FastAPI come framework web asincrono
- Architettura modulare con router separati per ogni dominio funzionale
- Worker separato per operazioni CPU-bound e I/O intensive
- Persistenza su filesystem (nessun database esterno necessario)

FLUSSO DI AVVIO:
1. Configurazione logging
2. Creazione app FastAPI con documentazione OpenAPI
3. Configurazione CORS per comunicazione con frontend React
4. Caricamento dinamico di tutti i router (con graceful degradation)
5. Evento di startup: verifica connettività Ollama + warmup modello embedding
6. Esposizione endpoint /api/health per health check

GESTIONE ERRORI:
- Se il caricamento di un router fallisce, gli altri vengono comunque caricati
- Se l'intera app non può avviarsi, viene creata un'app minimale che riporta
  l'errore nell'health check (evita che il container Docker si fermi)
"""

import logging
import traceback

# =============================================================================
# CONFIGURAZIONE LOGGING
# =============================================================================
# Formato: [TIMESTAMP] [LIVELLO] NOME_LOGGER: MESSAGGIO
# Livello DEBUG per tracciare ogni operazione durante lo sviluppo
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("koji")


# =============================================================================
# FACTORY DELL'APPLICAZIONE
# =============================================================================
def create_app():
    """
    Factory pattern per creare l'istanza dell'applicazione FastAPI.
    
    Returns:
        FastAPI: Applicazione configurata con tutti i router e middleware
        
    Note:
        La factory permette di creare multiple istanze dell'app (utile per test)
        e di gestire errori di inizializzazione in modo controllato.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from app.config import settings

    # Creazione dell'app FastAPI con metadati per documentazione OpenAPI
    app = FastAPI(
        title="Koji API",
        description="Piattaforma locale di gestione della conoscenza",
        version="1.0.0",
        docs_url="/api/docs",        # Documentazione Swagger UI
        redoc_url="/api/redoc",      # Documentazione ReDoc
        openapi_url="/api/openapi.json",  # Schema OpenAPI JSON
    )

    # -------------------------------------------------------------------------
    # MIDDLEWARE CORS
    # -------------------------------------------------------------------------
    # Necessario per permettere al frontend React (su porta 3000) di comunicare
    # con il backend (su porta 8000). In produzione gli origin dovrebbero essere
    # limitati ai domini effettivi.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,      # Permette cookie/auth headers
        allow_methods=["*"],         # Tutti i metodi HTTP
        allow_headers=["*"],         # Tutti gli header
    )

    # -------------------------------------------------------------------------
    # CARICAMENTO DINAMICO ROUTER
    # -------------------------------------------------------------------------
    # I router vengono importati uno per uno con gestione errori: se un router
    # fallisce (es. dipendenza mancante), gli altri vengono comunque caricati.
    # Questo garantisce che un modulo rotto non blocchi l'intera API.
    routers = [
        ("documents", "app.routers.documents"),    # Gestione documenti (CRUD)
        ("search", "app.routers.search"),          # Ricerca nella KB
        ("jobs", "app.routers.jobs"),              # Coda job di processing
        ("rag", "app.routers.rag"),                # Interrogazione RAG
        ("graph", "app.routers.graph"),            # Knowledge Graph
        ("wiki", "app.routers.wiki"),              # Wiki semantica
        ("models", "app.routers.models_route"),    # Gestione modelli LLM
        ("monitoring", "app.routers.monitoring"),  # Metriche live
        ("benchmarks", "app.routers.benchmarks"),  # Esperimenti riproducibili
        ("system", "app.routers.system"),          # Stato sistema
        ("admin", "app.routers.admin"),            # Configurazione admin
    ]

    for name, module_path in routers:
        try:
            # Import dinamico del modulo router
            mod = __import__(module_path, fromlist=["router"])
            # Registra il router con prefisso /api
            app.include_router(mod.router, prefix="/api")
            logger.info("Router caricato: %s", name)
        except Exception as e:
            # Log dell'errore ma continua con gli altri router
            logger.error("Router FALLITO: %s — %s", name, e)
            logger.debug(traceback.format_exc())

    # -------------------------------------------------------------------------
    # ENDPOINT HEALTH CHECK
    # -------------------------------------------------------------------------
    # Usato da Docker, load balancer e monitoring per verificare che l'app
    # sia in esecuzione e risponda correttamente.
    @app.get("/api/health")
    async def health_check():
        """Endpoint di health check per monitoring e orchestratori."""
        return {"status": "ok", "service": "koji-api"}

    # -------------------------------------------------------------------------
    # EVENTO DI STARTUP
    # -------------------------------------------------------------------------
    # Eseguito una volta all'avvio del server, prima che inizi ad accettare
    # richieste. Verifica le dipendenze esterne e pre-carica i modelli.
    @app.on_event("startup")
    async def on_startup():
        """
        Inizializzazione all'avvio del server.
        
        Operazioni eseguite:
        1. Log dei parametri di configurazione principali
        2. Verifica connettività con Ollama (servizio LLM)
        3. Warmup del modello di embedding (evita timeout alla prima query)
        """
        logger.info("==========================================")
        logger.info("  KOJI — Avvio in corso")
        logger.info("==========================================")
        logger.info("Ollama URL:  %s", settings.OLLAMA_BASE_URL)
        logger.info("Data dir:    %s", settings.DATA_DIR)

        # Verifica che Ollama sia raggiungibile
        # Se non lo è, il RAG non sarà disponibile ma l'app continua a funzionare
        # (upload, ricerca, wiki, grafo restano operativi)
        try:
            from app.services.llm_manager import llm_manager
            ok = await llm_manager.check_health()
            if ok:
                logger.info("Ollama:      CONNESSO")
            else:
                logger.warning("Ollama:      non raggiungibile — RAG non disponibile")
        except Exception as e:
            logger.warning("Ollama:      errore verifica — %s", e)

        # -------------------------------------------------------------------------
        # WARMUP MODELLO EMBEDDING
        # -------------------------------------------------------------------------
        # Il modello di embedding viene caricato in lazy loading al primo uso.
        # In un container Docker con risorse limitate, il primo caricamento
        # può superare il timeout di 30s. Eseguiamo il warmup ora in un thread
        # separato per evitare che la prima query RAG/ricerca vada in timeout.
        logger.info("Caricamento modello embedding '%s'...", settings.EMBEDDING_MODEL)
        try:
            from app.services.embedding_service import embedding_service
            # asyncio.to_thread esegue la funzione in un thread separato
            # per non bloccare l'event loop di FastAPI
            import asyncio
            await asyncio.to_thread(embedding_service.warmup)
            logger.info("Modello embedding caricato con successo.")
        except Exception as e:
            logger.warning("Modello embedding non caricato: %s", e)
            logger.warning("Il modello verrà caricato al primo uso (possibile timeout).")

        logger.info("==========================================")
        logger.info("API pronta su http://0.0.0.0:8000")
        logger.info("Docs:  http://localhost:8000/api/docs")
        logger.info("==========================================")

    return app


# =============================================================================
# CREAZIONE DELL'APP CON GESTIONE CRASH
# =============================================================================
# Se la factory fallisce (es. errore di configurazione grave), creiamo un'app
# minimale che riporta l'errore nell'health check. Questo evita che il container
# Docker si fermi completamente e permette di diagnosticare il problema.
_startup_error = None
try:
    app = create_app()
except Exception as e:
    logger.critical("FATALE all'avvio: %s", e)
    logger.critical(traceback.format_exc())
    # Rendi persistente il messaggio di errore: in Python 3 la variabile 'e'
    # viene eliminata alla fine del blocco except, quindi la salviamo in una
    # variabile esterna per poterla usare nell'endpoint /api/health
    _startup_error = str(e)
    # App minimale: solo health check con errore
    from fastapi import FastAPI
    app = FastAPI(title="Koji API — ERRORE AVVIO")

    @app.get("/api/health")
    async def health_check():
        """Health check che riporta l'errore di avvio."""
        return {"status": "error", "message": _startup_error}