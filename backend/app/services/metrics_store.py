"""
Metrics Store — Registro runtime delle metriche della piattaforma (BE-RF-21).

Raccoglie in memoria gli eventi misurati dai servizi (RAG, ricerca, LLM,
processing) e li espone in forma aggregata all'endpoint /api/monitoring/live.

Le metriche sono *runtime*: non vengono persistite (a differenza dei risultati
dei benchmark). Ogni misura chiusa viene inserita in un buffer circolare
(maxlen) con un timestamp; gli aggregati (media, conteggi) sono calcolati
al momento della lettura.

Classi di metriche:
- LLM:     modello, token, ttft, durata, tok/s
- RESI:    recupero (latency, numero risultati, dimensione indice)
- PROCESS: durata per fase del processing documenti
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional


class _RingBuffer:
    """Buffer circolare thread-safe con accesso agli aggregati."""

    def __init__(self, maxlen: int = 500):
        self._data: deque = deque(maxlen=maxlen)

    def push(self, item: dict):
        self._data.append(item)

    def snapshot(self) -> list[dict]:
        return list(self._data)

    def __len__(self):
        return len(self._data)


class MetricsStore:
    """Registro centrale delle metriche runtime della piattaforma."""

    def __init__(self, maxlen: int = 500):
        self._lock = threading.Lock()
        self.llm_metrics = _RingBuffer(maxlen)
        self.retrieval_metrics = _RingBuffer(maxlen)
        self.processing_metrics = _RingBuffer(maxlen)
        self._started_at = time.time()

    # --- LLM ---

    def record_llm(self, *, model: str, tokens: int, ttft: float,
                   duration_s: float, tok_per_sec: float,
                   error: Optional[str] = None, mode: str = "rag"):
        """Registra una generazione LLM completata (o fallita)."""
        with self._lock:
            self.llm_metrics.push({
                "ts": datetime.now().isoformat(),
                "model": model,
                "tokens": tokens,
                "ttft": round(ttft, 3),
                "duration_s": round(duration_s, 3),
                "tok_per_sec": round(tok_per_sec, 2),
                "mode": mode,
                "error": error,
            })

    def llm_summary(self) -> dict:
        """Aggregati delle ultime generazioni LLM."""
        with self._lock:
            items = self.llm_metrics.snapshot()
        if not items:
            return {"requests": 0}
        ok = [i for i in items if not i.get("error")]
        last = items[-1]
        rates = [i["tok_per_sec"] for i in ok if i.get("tok_per_sec")]
        return {
            "requests": len(items),
            "failed": len(items) - len(ok),
            "avg_tok_per_sec": round(sum(rates) / len(rates), 2) if rates else 0.0,
            "avg_ttft_s": round(sum(i["ttft"] for i in ok) / len(ok), 3) if ok else None,
            "avg_duration_s": round(sum(i["duration_s"] for i in ok) / len(ok), 3) if ok else None,
            "last": last,
        }

    # --- Retrieval ---

    def record_retrieval(self, *, query: str, mode: str, latency_ms: float,
                         num_results: int, index_size: int):
        """Registra una ricerca/recupero sulla KB."""
        with self._lock:
            self.retrieval_metrics.push({
                "ts": datetime.now().isoformat(),
                "query": query[:200],
                "mode": mode,
                "latency_ms": round(latency_ms, 2),
                "num_results": num_results,
                "index_size": index_size,
            })

    def retrieval_summary(self) -> dict:
        """Aggregati delle ultime operazioni di retrieval."""
        with self._lock:
            items = self.retrieval_metrics.snapshot()
        if not items:
            return {"requests": 0}
        lat = [i["latency_ms"] for i in items]
        return {
            "requests": len(items),
            "avg_latency_ms": round(sum(lat) / len(lat), 2),
            "last_latency_ms": lat[-1],
            "last": items[-1],
        }

    # --- Processing documenti ---

    def record_processing(self, *, doc_id: str, phase: str, duration_s: float,
                          filename: str = ""):
        """Registra la durata di una fase della pipeline documentale."""
        with self._lock:
            self.processing_metrics.push({
                "ts": datetime.now().isoformat(),
                "doc_id": doc_id,
                "filename": filename,
                "phase": phase,
                "duration_s": round(duration_s, 3),
            })

    def processing_summary(self) -> dict:
        """Durata media per fase della pipeline di processing."""
        with self._lock:
            items = self.processing_metrics.snapshot()
        if not items:
            return {"phases": {}}
        by_phase: dict[str, list[float]] = {}
        for i in items:
            by_phase.setdefault(i["phase"], []).append(i["duration_s"])
        return {
            "events": len(items),
            "phases": {
                phase: {
                    "count": len(durations),
                    "avg_s": round(sum(durations) / len(durations), 3),
                    "last_s": durations[-1],
                }
                for phase, durations in by_phase.items()
            },
        }

    # --- Uptime / generici ---

    def uptime_s(self) -> float:
        return time.time() - self._started_at


# Istanza singleton
metrics_store = MetricsStore()