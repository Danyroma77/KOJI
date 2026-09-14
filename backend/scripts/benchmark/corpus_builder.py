# backend/scripts/benchmark/corpus_builder.py
import random
from dataclasses import dataclass, field
from typing import List, Dict
import json
import numpy as np

random.seed(42)
np.random.seed(42)

@dataclass
class Document:
    doc_id: str
    title: str
    sections: List[Dict]

@dataclass
class Query:
    query_id: str
    text: str
    relevant_docs: List[Dict]

def build_corpus_and_queries():
    documents = [
        Document(
            doc_id="doc-1",
            title="Architettura del software",
            sections=[
                {
                    "section_id": "1.1",
                    "heading": "Microservizi",
                    "content": "L'architettura a microservizi suddivide l'applicazione in piccoli servizi indipendenti che communicano tramite API REST. Ogni servizio gestisce una funzionalità specifica e può essere sviluppato, distribuito e scalato autonomamente."
                },
                {
                    "section_id": "1.2",
                    "heading": "Database",
                    "content": "Per lo storage dei dati si utilizza un database relazionale PostgreSQL, scelto per la sua affidabilità e le prestazioni ottime nelle operazioni transazionali. Per le ricerche full-text è configurato Elasticsearch."
                },
                {
                    "section_id": "1.3",
                    "heading": "Cache",
                    "content": "Viene utilizzato Redis come layer di caching per ridurre il carico sui database e migliorare le prestazioni delle operazioni di lettura ripetute."
                },
            ]
        ),
        # ... altri documenti ...
    ]

    queries = [
        Query(query_id="q1", text="Quale approccio architetturale suddivide l'applicazione in servizi autonomi?", relevant_docs=[{"doc_id": "doc-1", "section_id": "1.1"}]),
        # ... altre query ...
    ]

    return documents, queries

def save_corpus_and_queries(documents, queries, results_dir):
    with open(results_dir / "corpus.json", "w") as f:
        json.dump([{"doc_id": d.doc_id, "title": d.title, "sections": d.sections} for d in documents], f, indent=2)
    with open(results_dir / "queries.json", "w") as f:
        json.dump([{"query_id": q.query_id, "text": q.text, "relevant_docs": q.relevant_docs} for q in queries], f, indent=2)
