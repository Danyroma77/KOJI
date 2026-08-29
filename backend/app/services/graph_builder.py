"""
Graph Builder — Estrae entità e relazioni dai documenti
tramite LLM locale, costruisce grafo NetworkX, serializza in JSON.
"""

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.llm_manager import llm_manager


GRAPH_EXTRACTION_PROMPT = """Analizza il testo ed estrai entità e relazioni.
Restituisci SOLO un array JSON di oggetti con formato:
[{{"subject": "...", "predicate": "...", "object": "...", "subject_type": "...", "object_type": "...", "confidence": 0.9}}]

Regole:
- Le entità devono essere nominate ESPPLICITAMENTE nel testo (nomi propri, termini tecnici, concetti citati). NON inventare entità
- Il campo type descrive la natura dell'entità così come emerge dal testo stesso: NON usare categorie predefinite, la tassonomia è libera
- Estrai solo relazioni esplicite nel testo, non inferite
- subject e object devono essere diversi tra loro
- La confidence deve riflettere la certezza che la relazione esista nel testo (0.0-1.0)
- Ignora riferimenti generici senza denominazione specifica (articoli, pronomi, ruoli anonimi)
- Se non ci sono entità o relazioni significative, restituisci []
- Massimo 15 triple per testo

TESTO:
{text}"""

GRAPH_DEDUP_SIMILARITY_THRESHOLD = 0.92

# Etichette non valide come entità: segnaposto dell'esempio del prompt e valori
# nulli. Filtro generico, indipendente dal dominio dei documenti.
_INVALID_LABELS = {
    "entità a", "entità b", "entita a", "entita b", "entity a", "entity b",
    "tipoa", "tipob", "type a", "type b", "n/a", "null", "none", "unknown",
}


class GraphBuilder:
    """Costruisce il Knowledge Graph dalla documentazione."""

    def __init__(self):
        self.graph_file = settings.GRAPH_FILE
        self._graph = None

    def _load_graph(self) -> dict:
        """Carica il grafo dal disco o inizializza vuoto."""
        if self._graph is not None:
            return self._graph

        if self.graph_file.exists():
            self._graph = json.loads(self.graph_file.read_text(encoding="utf-8"))
        else:
            self._graph = {"nodes": [], "edges": []}
        return self._graph

    def _save_graph(self):
        """Salva il grafo su disco."""
        self.graph_file.parent.mkdir(parents=True, exist_ok=True)
        self.graph_file.write_text(
            json.dumps(self._graph, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def extract_from_document(self, doc_id: str, text: str, title: str) -> int:
        """Estrae triple da un documento usando il LLM.

        Args:
            doc_id: ID del documento.
            text: Testo normalizzato.
            title: Titolo del documento.

        Returns:
            Numero di triple estratte.
        """
        graph = self._load_graph()

        # Dividi il testo in segmenti per non superare il contesto
        segments = self._split_for_extraction(text)

        all_triples = []
        for segment in segments:
            prompt = GRAPH_EXTRACTION_PROMPT.format(text=segment)
            try:
                response = await llm_manager.generate(
                    prompt=prompt,
                    max_tokens=1024,
                    temperature=0.1,
                )
                triples = self._parse_response(response)
                all_triples.extend(triples)
            except Exception as e:
                print(f"[GraphBuilder] Errore estrazione da {doc_id}: {e}")

        # Filtra per confidence
        threshold = settings.GRAPH_CONFIDENCE_THRESHOLD
        filtered = [t for t in all_triples if t.get("confidence", 0) >= threshold]

        # Deduplica nodi e aggiungi al grafo
        added = 0
        for triple in filtered:
            s_node = self._add_node(graph, triple["subject"], triple.get("subject_type", ""), doc_id)
            o_node = self._add_node(graph, triple["object"], triple.get("object_type", ""), doc_id)

            # Controlla se l'arco esiste già
            edge_exists = any(
                e["source"] == s_node["id"] and e["target"] == o_node["id"] and e["label"] == triple["predicate"]
                for e in graph["edges"]
            )
            if not edge_exists:
                graph["edges"].append({
                    "source": s_node["id"],
                    "target": o_node["id"],
                    "label": triple["predicate"],
                    "confidence": triple.get("confidence", 0.8),
                    "doc_id": doc_id,
                })
                added += 1

        self._save_graph()
        return added

    def _add_node(self, graph: dict, label: str, type_: str, doc_id: str) -> dict:
        """Aggiunge un nodo al grafo con deduplicazione fuzzy."""
        # Cerca nodo esistente con label simile
        for node in graph["nodes"]:
            if self._similarity(node["label"].lower(), label.lower()) >= GRAPH_DEDUP_SIMILARITY_THRESHOLD:
                # Aggiungi doc_id ai documenti se non presente
                if doc_id not in node.get("documents", []):
                    node.setdefault("documents", []).append(doc_id)
                return node

        # Nodo nuovo
        node_id = self._slugify(label)
        # Assicura ID unico
        existing_ids = {n["id"] for n in graph["nodes"]}
        suffix = 1
        while node_id in existing_ids:
            node_id = f"{self._slugify(label)}_{suffix}"
            suffix += 1

        node = {
            "id": node_id,
            "label": label,
            "type": (type_ or "").strip() or "Non classificato",
            "documents": [doc_id],
        }
        graph["nodes"].append(node)
        return node

    def _split_for_extraction(self, text: str, max_chars: int = 3000) -> list[str]:
        """Divide il testo in segmenti adatti all'estrazione."""
        if len(text) <= max_chars:
            return [text]

        segments = []
        paragraphs = text.split("\n\n")
        current = ""

        for para in paragraphs:
            if len(current) + len(para) > max_chars:
                if current:
                    segments.append(current)
                current = para
            else:
                current = current + "\n\n" + para if current else para

        if current:
            segments.append(current)

        return segments

    def _parse_response(self, response: str) -> list[dict]:
        """Parse della risposta LLM in triple."""
        # Estrai JSON dalla risposta
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if not json_match:
            return []

        try:
            triples = json.loads(json_match.group())
            # Valida formato: nessuna tassonomia predefinita. Vengono scartate
            # triple malformate o con entità segnaposto/fittizie.
            valid = []
            for t in triples:
                if not all(k in t for k in ("subject", "predicate", "object")):
                    continue
                if not self._valid_entity_label(t["subject"]) or not self._valid_entity_label(t["object"]):
                    continue
                # Soggetto e oggetto coincidenti non rappresentano una relazione
                if t["subject"].strip().lower() == t["object"].strip().lower():
                    continue
                t.setdefault("subject_type", "")
                t.setdefault("object_type", "")
                t.setdefault("confidence", 0.7)
                valid.append(t)
            return valid
        except json.JSONDecodeError:
            return []

    @staticmethod
    def _valid_entity_label(label) -> bool:
        """True se l'etichetta è una denominazione plausibile di entità.

        Controllo puramente strutturale (lunghezza, contenuto, segnaposto
        dell'esempio del prompt): nessun dominio o categoria è predefinito.
        """
        if not isinstance(label, str):
            return False
        cleaned = label.strip()
        if len(cleaned) < 2 or len(cleaned) > 80:
            return False
        if cleaned.lower() in _INVALID_LABELS:
            return False
        # Solo cifre o senza caratteri alfanumerici: non è un'entità
        if cleaned.isdigit() or not re.search(r"[\wà-ÿ]", cleaned, re.IGNORECASE):
            return False
        return True

    def _similarity(self, a: str, b: str) -> float:
        """Similarità semplice basata su sovrapposizione di parole."""
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    def _slugify(self, text: str) -> str:
        """Converte label in ID slug."""
        text = text.lower().strip()
        text = re.sub(r"[àáâãäå]", "a", text)
        text = re.sub(r"[èéêë]", "e", text)
        text = re.sub(r"[ìíîï]", "i", text)
        text = re.sub(r"[òóôõö]", "o", text)
        text = re.sub(r"[ùúûü]", "u", text)
        text = re.sub(r"[^a-z0-9]+", "_", text)
        return text.strip("_")[:40] or "node"

    def remove_by_doc(self, doc_id: str):
        """Rimuove nodi e archi associati a un documento."""
        graph = self._load_graph()

        # Trova nodi che hanno solo questo documento
        nodes_to_remove = set()
        for node in graph["nodes"]:
            docs = node.get("documents", [])
            if doc_id in docs:
                docs.remove(doc_id)
                if not docs:
                    nodes_to_remove.add(node["id"])

        # Rimuovi nodi
        graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in nodes_to_remove]

        # Rimuovi archi
        graph["edges"] = [
            e for e in graph["edges"]
            if e.get("doc_id") != doc_id
            and e["source"] not in nodes_to_remove
            and e["target"] not in nodes_to_remove
        ]

        self._save_graph()

    def get_graph(self) -> dict:
        """Restituisce il grafo completo."""
        return self._load_graph()

    def get_node_detail(self, node_id: str) -> Optional[dict]:
        """Restituisce dettagli di un nodo con storytelling e collegamenti."""
        graph = self._load_graph()
        node = next((n for n in graph["nodes"] if n["id"] == node_id), None)
        if not node:
            return None

        # Trova collegamenti
        links = []
        for edge in graph["edges"]:
            if edge["source"] == node_id:
                target = next((n for n in graph["nodes"] if n["id"] == edge["target"]), None)
                if target:
                    links.append({"relation": edge["label"], "target": target["label"], "target_id": target["id"]})
            elif edge["target"] == node_id:
                source = next((n for n in graph["nodes"] if n["id"] == edge["source"]), None)
                if source:
                    links.append({"relation": f"{edge['label']} (inverso)", "target": source["label"], "target_id": source["id"]})

        return {
            "id": node["id"],
            "label": node["label"],
            "type": node["type"],
            "degree": len(links),
            "documents": node.get("documents", []),
            "storytelling": f"{node['label']} è un'entità di tipo {node['type']} presente nella Knowledge Base. Partecipa a {len(links)} relazioni con altre entità del grafo. Presente in {len(node.get('documents', []))} documento/i.",
            "links": links,
        }


# Istanza singleton
graph_builder = GraphBuilder()