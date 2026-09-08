# KOJI - Knowledge Organization & Joint Intelligence

Piattaforma per la gestione e interrogazione della conoscenza basata su LLM locali.

## 🚀 Avvio Rapido

```bash
# 1. Setup iniziale
./scripts/init.sh

# 2. Oppure avvio manuale
docker-compose up -d
```

## 🔌 API (FastAPI)

Docs interattive: `http://localhost:8000/api/docs` — tutte le route sotto `/api`.

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| POST | `/api/documents/upload` | Upload multi-file + validazione (estensione, dimensione) |
| GET  | `/api/documents` | Catalogo documenti (stato, chunk, metadati) |
| PATCH| `/api/documents/{id}` | Modifica metadati (BE-RF-09) |
| GET  | `/api/documents/{id}/text` | Testo normalizzato |
| GET  | `/api/documents/{id}/download` | Download file originale |
| DELETE | `/api/documents/{id}` · `/all` | Eliminazione (con artefatti derivati) |
| POST | `/api/documents/{id}/reprocess` | Riprocessamento file originale |
| POST | `/api/documents/{id}/regenerate-wiki` · `/regenerate-graph` | Rigenerazione artefatti |
| GET  | `/api/documents/activities` | Cronologia attività KB |
| GET  | `/api/jobs` · `/api/jobs/{id}` | Stato job con durata ed errore (BE-RF-10) |
| POST | `/api/search` | Ricerca Dense / BM25 / Hybrid (RRF) + rerank opzionale |
| POST | `/api/rag/query` | Query RAG in streaming SSE con fonti e metriche |
| GET  | `/api/models/catalog` | Catalogo modelli con stato rispetto a Ollama |
| POST | `/api/models/pull` · `/select` · `/load` · `/unload` | Gestione modelli |
| GET  | `/api/wiki/index` · `/api/wiki/page/{id}` | Wiki semantica |
| POST | `/api/wiki/rebuild` | Rigenerazione Wiki |
| GET  | `/api/graph` · `/api/graph/node/{id}` | Knowledge Graph |
| POST | `/api/graph/rebuild` | Rigenerazione Graph (reset default: entità ri-estratte a runtime e ancorate al testo dei documenti) |
| GET  | `/api/monitoring/live` | Metriche runtime (CPU/RAM/retrieval/LLM/job) |
| GET  | `/api/system/metrics` · `/api/system/status` | Metriche/stato servizi |
| GET/PUT | `/api/admin/config` | Parametri configurazione |
| POST | `/api/benchmarks/run` | Avvio benchmark (E1–E7) |
| GET  | `/api/benchmarks` · `/api/benchmarks/{id}` | Stato/risultati benchmark |

## 🧪 Benchmark (BE-RF-22)

Avvio: `POST /api/benchmarks/run` con body:

```json
{
  "experiment": "E4",
  "questions": [
    {"question": "Qual è la procedura per ottenere il rimborso?",
     "relevant_docs": ["abc12345"]}
  ],
  "top_k": 10
}
```

Esperimenti supportati: `E1` Confronto LLM, `E2` Quantizzazione, `E3` Originale vs normalizzato,
`E4` BM25 vs Dense vs Hybrid, `E5` LLM vs RAG, `E6` KB/Wiki/Graph, `E7` Scalabilità.
Ogni run è persistita in `DATA_DIR/<dataset>/benchmarks/<run_id>.json` con configurazione,
ambiente e metriche per la riproducibilità.

## ⚙️ Configurazione

Le variabili d'ambiente (prefisso `KOJI_`) controllano chunking, embedding, retrieval e upload — vedi `.env.example` per tutti i parametri.
