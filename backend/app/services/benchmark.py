"""
Benchmark Service — Esecuzione di esperimenti riproducibili (BE-RF-22).

Supporta gli esperimenti della specifica operativa (sezione 12):
- E1 Confronto LLM           — risposta diretta LLM su più modelli
- E2 Quantizzazione          — confronto varianti quantizzate (tag modello)
- E3 Originale vs normalizzato — retrieval su testo grezzo vs normalizzato
- E4 BM25 vs Dense vs Hybrid  — metriche di retrieval + latency
- E5 LLM vs RAG               — generazione diretta vs con contesto
- E6 KB / Wiki / Graph        — confronto delle rappresentazioni
- E7 Scalabilità              — memoria/tempo al crescere della KB

Ogni run viene persistita come JSON in BENCHMARKS_DIR/{run_id}.json:
configurazione, dataset, misure per-domanda e aggregati vengono salvati
per garantire la riproducibilità delle run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import platform
import time
import uuid
from datetime import datetime
from typing import Optional

import psutil

from app.config import settings
from app.models import BenchmarkConfig

logger = logging.getLogger("koji")


def chunk_doc_id(chunk_id: str) -> str:
    """Riduce un ID chunk '{doc_id}_{index}' al suo documento."""
    return str(chunk_id).rsplit("_", 1)[0]


# Cache testi grezzi per E3 (parsing pigro dei file raw)
_raw_text_cache: dict[str, str] = {}


def _is_relevant(doc_id: str, relevant_ids: list[str]) -> bool:
    """Confronto per ID documento esatto o contenuto."""
    for rel in relevant_ids:
        if not rel:
            continue
        if doc_id == rel or rel in doc_id or doc_id in rel:
            return True
    return False


def recall_at_k(results: list[dict], relevant_ids: list[str], k: int) -> Optional[float]:
    """Recall@K sul sottoinsieme rilevante con ground-truth fornito."""
    if not relevant_ids:
        return None
    relevant = {r for r in relevant_ids if r}
    if not relevant:
        return None
    hits = {chunk_doc_id(r["id"]) for r in results[:k]}
    return round(len(hits & relevant) / len(relevant), 4)


def mrr(results: list[dict], relevant_ids: list[str]) -> Optional[float]:
    """Mean Reciprocal Rank (primo risultato rilevante)."""
    if not relevant_ids:
        return None
    for i, r in enumerate(results, start=1):
        if _is_relevant(chunk_doc_id(r["id"]), relevant_ids):
            return round(1.0 / i, 4)
    return 0.0


def ndcg_at_k(results: list[dict], relevant_ids: list[str], k: int) -> Optional[float]:
    """nDCG@K con rilevanza binaria."""
    if not relevant_ids:
        return None
    dcg = 0.0
    for i, r in enumerate(results[:k], start=1):
        rel = 1 if _is_relevant(chunk_doc_id(r["id"]), relevant_ids) else 0
        dcg += rel / math.log2(i + 1)
    relevant = [r for r in relevant_ids if r]
    idcg = sum(1 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    if idcg <= 0:
        return None
    return round(dcg / idcg, 4)


class BenchmarkService:
    """Esegue run benchmark persistenti in background."""

    def __init__(self):
        self.dir = settings.BENCHMARKS_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        # Run attualmente in esecuzione in questo processo
        self._active: set[str] = set()
        # Cache testi grezzi per E3 (parsing pigro dei file raw)
        self._raw_texts: dict[str, str] = {}

    # --- Persistenza ------------------------------------------------------

    def _path(self, run_id: str):
        return self.dir / f"{run_id}.json"

    def _load(self, run_id: str) -> Optional[dict]:
        path = self._path(run_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save(self, run: dict):
        self._path(run["run_id"]).write_text(
            json.dumps(run, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _update(self, run_id: str, **changes):
        run = self._load(run_id)
        if run:
            run.update(changes)
            self._save(run)

    def create_run(self, config: BenchmarkConfig) -> dict:
        """Crea la run con stato pending e la persiste."""
        run = {
            "run_id": uuid.uuid4().hex[:12],
            "experiment": config.experiment.value,
            "label": config.label,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "finished_at": None,
            "duration_s": None,
            "error": None,
            "progress": 0.0,
            "config": config.model_dump(mode="json"),
            "environment": self._environment(config),
            "summary": {},
            "results": {},
        }
        self._save(run)
        return run

    def _environment(self, config: BenchmarkConfig) -> dict:
        """Snapshot dell'ambiente per riproducibilità."""
        env = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "ram_total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 1),
            "chunk_size": settings.CHUNK_SIZE,
            "chunk_overlap_pct": settings.CHUNK_OVERLAP_PCT,
            "embedding_model": settings.EMBEDDING_MODEL,
            "retrieval_mode": settings.RAG_RETRIEVAL_MODE,
            "rerank_enabled": settings.RAG_RERANK_ENABLED,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            from app.services.vector_store import vector_store
            vector_store.initialize()
            env["kb_chunks"] = vector_store.count
        except Exception:
            env["kb_chunks"] = 0
        try:
            from app.routers.documents import _load_catalog
            catalog = _load_catalog()
            env["kb_documents"] = len(catalog.get("documents", []))
        except Exception:
            env["kb_documents"] = 0
        return env
# --- Esecuzione -------------------------------------------------------

    def _load_questions(self, config: BenchmarkConfig) -> list[dict]:
        """Carica e normalizza le domande del benchmark.

        Fonte: `config.questions` (inline) oppure `config.dataset_file`
        (JSON con chiave "questions"). Ogni domanda: {"question": str,
        "relevant_docs": [doc_id, ...]}.
        """
        questions = []
        if config.questions:
            questions = list(config.questions)
        elif config.dataset_file:
            path = settings.BENCHMARK_DATASET_FILE
            if config.dataset_file not in ("", "default"):
                candidate = settings.DATA_DIR / config.dataset_file
                if candidate.exists():
                    path = candidate
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                questions = data.get("questions", [])
        else:
            # Nessun dataset esplicito: usa un set minimo a partire dai doc pronti
            if settings.BENCHMARK_DATASET_FILE.exists():
                data = json.loads(settings.BENCHMARK_DATASET_FILE.read_text(encoding="utf-8"))
                questions = data.get("questions", [])

        normalized = []
        for q in questions:
            if isinstance(q, str):
                normalized.append({"question": q, "relevant_docs": []})
            elif isinstance(q, dict) and q.get("question"):
                normalized.append({
                    "question": str(q["question"]),
                    "relevant_docs": list(q.get("relevant_docs") or []),
                })
        if config.limit:
            normalized = normalized[: config.limit]
        if not normalized:
            raise ValueError("Nessuna domanda disponibile per il benchmark")
        return normalized

    def _progress(self, run_id: str, fraction: float):
        self._update(run_id, progress=round(min(1.0, max(0.0, fraction)), 4))

    def get_run(self, run_id: str) -> Optional[dict]:
        """Legge una run; quella "running" ma senza task attivo è interrotta."""
        run = self._load(run_id)
        if not run:
            return None
        if run.get("status") == "running" and run_id not in self._active:
            run["status"] = "failed"
            run["error"] = run.get("error") or "Run interrotta dal riavvio del servizio"
            run["finished_at"] = datetime.now().isoformat()
            self._save(run)
        return run

    def list_runs(self) -> list[dict]:
        runs = []
        for path in sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                runs.append(self.get_run(path.stem))
            except Exception:
                continue
        return runs

    async def start_run(self, run: dict, config: BenchmarkConfig):
        """Esegue la run in background aggiornando il file persistente."""
        run_id = run["run_id"]
        self._active.add(run_id)
        self._update(run_id, status="running", started_at=datetime.now().isoformat())
        t0 = time.time()
        try:
            questions = self._load_questions(config)
            handler = self._handlers().get(config.experiment.value)
            if not handler:
                raise ValueError(f"Esperimento non supportato: {config.experiment.value}")
            results, summary = await handler(run_id, config, questions)
            duration = time.time() - t0
            self._update(
                run_id,
                status="completed",
                finished_at=datetime.now().isoformat(),
                duration_s=round(duration, 3),
                progress=1.0,
                results=results,
                summary=summary,
            )
            logger.info("[%s] Benchmark %s COMPLETATO in %.1fs", run_id, config.experiment.value, duration)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("[%s] Benchmark %s FALLITO", run_id, config.experiment.value)
            self._update(
                run_id,
                status="failed",
                finished_at=datetime.now().isoformat(),
                duration_s=round(time.time() - t0, 3),
                error=str(e)[:500],
            )
        finally:
            self._active.discard(run_id)
# --- Helpers retrieval -----------------------------------------------

    async def _search(self, mode: str, question: str, config: BenchmarkConfig,
                      top_k: Optional[int] = None) -> tuple[list[dict], float]:
        """Esegue ricerca con modalità e misura la latenza in ms."""
        from app.services.vector_store import vector_store
        from app.services.embedding_service import embedding_service
        t0 = time.time()
        if mode == "dense":
            emb = embedding_service.embed_query(question)
            res = vector_store.dense_search(emb, top_k=top_k or config.top_k)
        elif mode == "bm25":
            res = vector_store.keyword_search(question, top_k=top_k or config.top_k)
        else:
            emb = embedding_service.embed_query(question)
            res = vector_store.hybrid_search(
                query=question,
                query_embedding=emb,
                top_k_dense=config.top_k_dense,
                top_k_keyword=config.top_k_keyword,
                rrf_k=config.rrf_k,
            )
        latency_ms = (time.time() - t0) * 1000
        return res, latency_ms

    async def _run_llm_compare(self, run_id: str, config: BenchmarkConfig,
                               questions: list[dict]) -> tuple[dict, dict]:
        """E1/E2 — confronto modelli LLM (o quantizzazioni) su risposta diretta."""
        from app.services.llm_manager import llm_manager
        models = config.models or [llm_manager.active_model or settings.OLLAMA_MODEL]
        per_model = {}
        total = len(models) * len(questions)
        done = 0
        for model in models:
            lat, toks, entries = [], [], []
            t_all = time.time()
            for q in questions:
                t0 = time.time()
                try:
                    answer = await llm_manager.generate(
                        q["question"], model=model,
                        temperature=config.temperature, max_tokens=config.max_tokens,
                    )
                    dt = time.time() - t0
                    tokens = len(answer) // 4
                    entries.append({
                        "question": q["question"],
                        "answer": answer,
                        "latency_s": round(dt, 3),
                        "tokens": tokens,
                        "error": None,
                    })
                    lat.append(dt)
                    toks.append(tokens)
                    from app.services.metrics_store import metrics_store
                    metrics_store.record_llm(
                        model=model, tokens=tokens, ttft=0.0, duration_s=dt,
                        tok_per_sec=tokens / max(dt, 0.001), mode="benchmark",
                    )
                except Exception as e:
                    entries.append({"question": q["question"], "error": str(e)})
                done += 1
                self._progress(run_id, done / total)
            per_model[model] = {
                "per_question": entries,
                "avg_latency_s": round(sum(lat) / len(lat), 3) if lat else None,
                "avg_tokens": round(sum(toks) / len(toks), 1) if toks else None,
                "total_s": round(time.time() - t_all, 3),
                "ram_percent": psutil.virtual_memory().percent,
                "model_size_bytes": await self._model_size(model),
            }
        summary = {
            "experiment": config.experiment.value,
            "models": {m: {k: v for k, v in d.items() if k != "per_question"}
                       for m, d in per_model.items()},
            "questions": len(questions),
        }
        return {"per_model": per_model}, summary

    async def _model_size(self, model: str) -> Optional[int]:
        try:
            from app.services.llm_manager import llm_manager
            tags = await llm_manager.list_models()
            for m in tags:
                if m.get("name") == model:
                    return m.get("size")
        except Exception:
            pass
        return None

    async def _run_retrieval_compare(self, run_id: str, config: BenchmarkConfig,
                                     questions: list[dict]) -> tuple[dict, dict]:
        """E4 — BM25 vs Dense vs Hybrid con metriche retrieval."""
        modes = ["bm25", "dense", "hybrid"]
        per_mode = {m: {"per_question": [], "latency_ms": [], "recall": [], "mrr": [], "ndcg": []}
                    for m in modes}
        total = len(modes) * len(questions)
        done = 0
        for mode in modes:
            for q in questions:
                rel = q.get("relevant_docs") or []
                try:
                    res, lat = await self._search(mode, q["question"], config)
                    per_mode[mode]["per_question"].append({
                        "question": q["question"],
                        "latency_ms": round(lat, 2),
                        "top_ids": [r["id"] for r in res[:5]],
                        "recall_at_k": recall_at_k(res, rel, config.top_k),
                        "mrr": mrr(res, rel),
                        "ndcg_at_k": ndcg_at_k(res, rel, config.top_k),
                    })
                    per_mode[mode]["latency_ms"].append(lat)
                    per_mode[mode]["recall"].append(recall_at_k(res, rel, config.top_k))
                    per_mode[mode]["mrr"].append(mrr(res, rel))
                    per_mode[mode]["ndcg"].append(ndcg_at_k(res, rel, config.top_k))
                except Exception as e:
                    per_mode[mode]["per_question"].append({"question": q["question"], "error": str(e)})
                done += 1
                self._progress(run_id, done / total)
        summary = {}
        for mode in modes:
            d = per_mode[mode]
            vals = {"avg_latency_ms": round(sum(d["latency_ms"]) / len(d["latency_ms"]), 2) if d["latency_ms"] else None}
            for key in ("recall", "mrr", "ndcg"):
                items = [v for v in d[key] if v is not None]
                vals[f"avg_{key}"] = round(sum(items) / len(items), 4) if items else None
            summary[mode] = vals
        return {"per_mode": per_mode}, {"experiment": "E4", "modes": summary, "questions": len(questions)}

    def _load_raw_text(self, doc: dict) -> Optional[str]:
        """Parsing pigro del file originale per il confronto E3.

        Il testo grezzo (pre-normalizzazione) viene estratto dal file raw e
        messo in cache: serve solo all'esperimento E3, quindi il costo di
        parsing è sostenuto una sola volta per documento.
        """
        doc_id = doc.get("id", "")
        if doc_id in _raw_text_cache:
            return _raw_text_cache[doc_id]
        raw_dir = settings.RAW_DIR
        candidates = list(raw_dir.glob(f"{doc_id}_*"))
        if not candidates:
            return None
        try:
            from app.services.document_parser import parse_document
            text = parse_document(candidates[0].read_bytes(), doc.get("filename", "doc")).text
        except Exception:
            return None
        _raw_text_cache[doc_id] = text
        return text

    async def _run_original_vs_normalized(self, run_id: str, config: BenchmarkConfig,
                                          questions: list[dict]) -> tuple[dict, dict]:
        """E3 — confronto retrieval/qualità su testo originale vs normalizzato.

        "Normalizzato" = KB indicizzata (ChromaDB + BM25). "Originale" = BM25
        in memoria costruito sui testi grezzi estratti dai file raw.
        """
        from app.routers.documents import _load_catalog
        from app.services.vector_store import vector_store
        catalog = _load_catalog().get("documents", [])
        doc_ids = [d["id"] for d in catalog]

        # Indice BM25 "originale" lazy: testi raw parsificati al primo uso
        raw_texts = {}
        for d in catalog:
            text = self._load_raw_text(d)
            if text and text.strip():
                raw_texts[d["id"]] = text
        raw_bm25 = None
        raw_bm25_docs = list(raw_texts.values())
        raw_bm25_ids = list(raw_texts.keys())
        if raw_bm25_docs:
            from rank_bm25 import BM25Okapi
            raw_bm25 = BM25Okapi([t.lower().split() for t in raw_bm25_docs])

        per_q = []
        lat_raw, lat_norm = [], []
        recall_raw, recall_norm = [], []
        for i, q in enumerate(questions):
            rel = q.get("relevant_docs") or []
            # --- Normalizzato: hybrid retrieval sulla KB indicizzata
            try:
                res_n, lat = await self._search("hybrid", q["question"], config)
                lat_norm.append(lat)
                recall_norm.append(recall_at_k(res_n, rel, config.top_k))
            except Exception as e:
                res_n, lat = [], None
                per_q.append({"question": q["question"], "normalized_error": str(e)})
                lat_norm.append(None)
                recall_norm.append(None)
            # --- Originale: BM25 in memoria sui testi grezzi
            try:
                t0 = time.time()
                if raw_bm25:
                    tokenized = q["question"].lower().split()
                    scores = raw_bm25.get_scores(tokenized)
                    ranked = sorted(zip(raw_bm25_ids, scores), key=lambda x: x[1], reverse=True)
                    hits = [{"id": rid, "score": s} for rid, s in ranked[: config.top_k]]
                    lat = (time.time() - t0) * 1000
                else:
                    hits, lat = [], 0.0
                lat_raw.append(lat)
                recall_raw.append(recall_at_k(hits, rel, config.top_k))
            except Exception as e:
                lat_raw.append(None)
                recall_raw.append(None)
                per_q.append({"question": q["question"], "raw_error": str(e)})
            per_q.append({
                "question": q["question"],
                "normalized_latency_ms": round(lat, 2) if lat else None,
                "raw_latency_ms": round(lat_raw[-1], 2) if lat_raw[-1] is not None else None,
                "normalized_recall_at_k": recall_norm[-1],
                "raw_recall_at_k": recall_raw[-1],
            })
            self._progress(run_id, (i + 1) / len(questions))

        def avg(items):
            vals = [v for v in items if v is not None]
            return round(sum(vals) / len(vals), 4) if vals else None

        summary = {
            "experiment": "E3",
            "normalized": {"avg_latency_ms": avg(lat_norm), "avg_recall_at_k": avg(recall_norm)},
            "original": {"avg_latency_ms": avg(lat_raw), "avg_recall_at_k": avg(recall_raw)},
            "raw_docs_parsed": len(raw_texts),
            "questions": len(questions),
        }
        return {"per_question": per_q, "documents": doc_ids}, summary

    async def _run_llm_vs_rag(self, run_id: str, config: BenchmarkConfig,
                               questions: list[dict]) -> tuple[dict, dict]:
        """E5 — generazione diretta LLM vs RAG (con contesto dalle fonti)."""
        from app.services.llm_manager import llm_manager
        from app.services.rag_engine import rag_engine
        model = (config.models or [llm_manager.active_model or settings.OLLAMA_MODEL])[0]
        per_q = []
        lat_llm, lat_rag = [], []
        for i, q in enumerate(questions):
            entry = {"question": q["question"]}
            try:
                t0 = time.time()
                answer = await llm_manager.generate(
                    q["question"], model=model,
                    temperature=config.temperature, max_tokens=config.max_tokens,
                )
                entry["direct"] = {"answer": answer, "latency_s": round(time.time() - t0, 3),
                                   "tokens": len(answer) // 4}
                lat_llm.append(time.time() - t0)
            except Exception as e:
                entry["direct_error"] = str(e)
            try:
                t0 = time.time()
                result = await rag_engine.query(
                    question=q["question"], model=model,
                    top_k=config.top_k, temperature=config.temperature,
                    max_tokens=config.max_tokens,
                )
                entry["rag"] = {
                    "answer": result.answer,
                    "latency_s": round(time.time() - t0, 3),
                    "sources": [s["document_name"] for s in result.sources],
                    "metrics": result.metrics,
                }
                lat_rag.append(time.time() - t0)
            except Exception as e:
                entry["rag_error"] = str(e)
            per_q.append(entry)
            self._progress(run_id, (i + 1) / len(questions))

        def avg(items):
            vals = [v for v in items if v is not None]
            return round(sum(vals) / len(vals), 3) if vals else None

        citations = sum(1 for e in per_q if e.get("rag", {}).get("sources"))
        summary = {
            "experiment": "E5",
            "model": model,
            "direct": {"avg_latency_s": avg(lat_llm), "answers": len(per_q)},
            "rag": {"avg_latency_s": avg(lat_rag), "answers": len(per_q),
                    "with_citations": citations},
            "questions": len(questions),
        }
        return {"per_question": per_q}, summary

    async def _run_kb_wiki_graph(self, run_id: str, config: BenchmarkConfig,
                                 questions: list[dict]) -> tuple[dict, dict]:
        """E6 — confronto rappresentazioni KB / Wiki / Graph."""
        from app.services.vector_store import vector_store
        from app.services.wiki_generator import wiki_generator
        from app.services.graph_builder import graph_builder

        kb = {"per_question": [], "latency_ms": []}
        for i, q in enumerate(questions):
            try:
                t0 = time.time()
                res, _ = await self._search("hybrid", q["question"], config)
                kb["per_question"].append({
                    "question": q["question"],
                    "top_docs": sorted({chunk_doc_id(r["id"]) for r in res[:5]}),
                    "latency_ms": round((time.time() - t0) * 1000, 2),
                })
                kb["latency_ms"].append((time.time() - t0) * 1000)
            except Exception as e:
                kb["per_question"].append({"question": q["question"], "error": str(e)})
            self._progress(run_id, 0.3 * (i + 1) / len(questions))

        # Wiki: BM25 in memoria sulle pagine generate
        wiki_index = wiki_generator.get_index()
        wiki_pages = []
        for group in wiki_index.get("groups", []):
            for item in group.get("items", []):
                page = wiki_generator.get_page(item["id"])
                if page:
                    wiki_pages.append(page)
        wiki_stats = {"pages": len(wiki_pages), "groups": len(wiki_index.get("groups", []))}

        # Graph: statistiche del grafo corrente
        graph = graph_builder.get_graph()
        graph_stats = {"nodes": len(graph.get("nodes", [])),
                       "edges": len(graph.get("edges", []))}

        self._progress(run_id, 0.6)
        wiki_queries = []
        from rank_bm25 import BM25Okapi
        wiki_bm25 = None
        if wiki_pages:
            wiki_bm25 = BM25Okapi(
                [(p["title"] + " " + p["content"]).lower().split() for p in wiki_pages]
            )
            for q in questions:
                t0 = time.time()
                scores = wiki_bm25.get_scores(q["question"].lower().split())
                ranked = sorted(zip(wiki_pages, scores), key=lambda x: x[1], reverse=True)
                wiki_queries.append({
                    "question": q["question"],
                    "top_pages": [
                        {"id": p["id"], "title": p["title"], "score": round(s, 3)}
                        for p, s in ranked[:3]
                    ],
                    "latency_ms": round((time.time() - t0) * 1000, 2),
                })
            self._progress(run_id, 0.9)

        avg_kb_latency = round(sum(kb["latency_ms"]) / len(kb["latency_ms"]), 2) if kb["latency_ms"] else None
        summary = {
            "experiment": "E6",
            "kb": {"avg_latency_ms": avg_kb_latency, "answers": len(kb["per_question"])},
            "wiki": wiki_stats,
            "graph": graph_stats,
            "questions": len(questions),
        }
        results = {"kb": kb, "wiki_pages": wiki_pages[: max(len(questions), 5)],
                   "wiki_queries": wiki_queries, "graph": graph_stats}
        return results, summary

    async def _run_scalability(self, run_id: str, config: BenchmarkConfig,
                               questions: list[dict]) -> tuple[dict, dict]:
        """E7 — snapshot memoria/tempo alla dimensione attuale della KB."""
        from app.services.vector_store import vector_store
        from app.services.metrics_store import metrics_store
        vector_store.initialize()
        chunks = vector_store.count

        lat = []
        per_q = []
        for i, q in enumerate(questions):
            try:
                res, lat_ms = await self._search("hybrid", q["question"], config)
                lat.append(lat_ms)
                per_q.append({"question": q["question"], "latency_ms": round(lat_ms, 2),
                              "num_results": len(res)})
            except Exception as e:
                per_q.append({"question": q["question"], "error": str(e)})
            self._progress(run_id, (i + 1) / len(questions))

        ram = psutil.virtual_memory()
        processing = metrics_store.processing_summary()
        measured = {
            "chunks": chunks,
            "documents": self._environment(config).get("kb_documents", 0),
            "ram_used_gb": round(ram.used / (1024 ** 3), 2),
            "ram_percent": ram.percent,
            "avg_retrieval_latency_ms": round(sum(lat) / len(lat), 2) if lat else None,
            "processing_phases": processing.get("phases", {}),
        }
        # Stima lineare estrapolata (ipotesi: latenza ~ lineare con i chunk)
        base_lat = measured["avg_retrieval_latency_ms"]
        estimated = {}
        if base_lat and chunks > 0:
            for factor, label in ((1, "1x"), (2, "2x"), (4, "4x")):
                estimated[label] = {
                    "est_chunks": chunks * factor,
                    "est_latency_ms": round(base_lat * factor, 2),
                    "est_ram_embedding_gb": round(chunks * 384 * 4 * factor / (1024 ** 3), 2),
                }
        summary = {"experiment": "E7", "measured": measured, "estimated": estimated,
                   "questions": len(questions)}
        return {"per_question": per_q, "measured": measured, "estimated": estimated}, summary

    def _handlers(self) -> dict:
        return {
            "E1": self._run_llm_compare,
            "E2": self._run_llm_compare,
            "E3": self._run_original_vs_normalized,
            "E4": self._run_retrieval_compare,
            "E5": self._run_llm_vs_rag,
            "E6": self._run_kb_wiki_graph,
            "E7": self._run_scalability,
        }


# Istanza singleton
benchmark_service = BenchmarkService()