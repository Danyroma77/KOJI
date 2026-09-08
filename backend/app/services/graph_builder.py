"""
=============================================================================
GRAPH BUILDER — ESTRAE ENTITÀ E RELAZIONI DAI DOCUMENTI TRAMITE LLM
=============================================================================

Estrae entità e relazioni dai documenti tramite LLM locale, costruisce
un grafo semantico e lo serializza in JSON per la visualizzazione.

ESTRAZIONE:
- Il LLM analizza il testo e identifica entità e relazioni
- Le entità devono essere "grounded" (citazioni letterali nel testo)
- Le relazioni descrivono connessioni esplicite tra entità
- Confidence assegnata in base alla certezza dell'estrazione

STRUTTURA GRAFO:
- Nodi: entità con label, tipo, grado, documenti di origine
- Archi: relazioni con label, confidence, documento di origine
- Metadati: grounding (testo esatto), confidence, tipo entità

VALIDAZIONE:
- Etichette max 60 caratteri (evita frasi intere)
- Entità devono essere nel testo originale (grounding)
- Confidence minima configurabile (default 0.7)
- Rimozione entità duplicate/simili (soglia 0.92)

PERSISTENZA:
- Grafo salvato in graph.json
- Aggiornamento incrementale per documento
- Rimozione selettiva per documento
"""

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.llm_manager import llm_manager


# Prompt per l'estrazione di entità e relazioni tramite LLM
# Richiede citazioni letterali (grounding) e formato JSON strutturato
GRAPH_EXTRACTION_PROMPT = """Analizza il TESTO ed estrai entità e relazioni tra loro.
Restituisci SOLO un array JSON di oggetti con formato:
[{{"subject": "...", "predicate": "...", "object": "...", "subject_type": "...", "object_type": "...", "confidence": 0.9}}]

Regole:
- "subject" e "object" sono CITAZIONI LETTERALI del TESTO: copia la sequenza di caratteri esattamente come appare (stesse parole, stesso idioma, stesso stato singular/plurale). NON parafrasare, NON tradurre, NON completare, NON usare conoscenze esterne
- Ogni entità è una denominazione specifica citata nel testo: nomi propri, nomi di componenti/sistemi/documenti/procedure, termini tecnici concreti. NON inventare entità
- NON usare come entità: parole generiche, verbi, intere frasi, i campi della risposta stessa ("subject", "predicate", "confidence")
- "predicate" descrive la relazione esplicita tra le due entità con 1-4 parole (es. "configura", "fa parte di", "dipende da")
- I campi *_type descrivono la natura dell'entità così come emerge dal testo: nessuna tassonomia predefinita, la tassonomia è libera
- Estrai solo relazioni esplicite nel testo, non inferite
- subject e object devono essere diversi tra loro
- La confidence (0.0-1.0) riflette la certezza che la relazione sia dichiarata nel testo
- Ignora riferimenti generici senza denominazione specifica (articoli, pronomi, ruoli anonimi)
- Se non ci sono entità o relazioni significative, restituisci []
- Massimo 15 triple per testo. Nessun testo fuori dall'array JSON

TESTO:
{text}"""

GRAPH_DEDUP_SIMILARITY_THRESHOLD = 0.92

# Etichette non valide come entità: segnaposto dell'esempio del prompt e valori
# nulli. Filtro generico, indipendente dal dominio dei documenti.
_INVALID_LABELS = {
    "entità a", "entità b", "entita a", "entita b", "entity a", "entity b",
    "tipoa", "tipob", "type a", "type b", "n/a", "null", "none", "unknown",
    "testo", "text", "subject", "object", "predicate", "confidence",
    "subject_type", "object_type",
}

# Parole funzionali (it/en): un'etichetta composta SOLO da queste non è
# una denominazione di entità. Lista generica, nessuna tassonomia di dominio.
_STOPWORD_TOKENS = frozenset({
    # italiano
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da",
    "in", "con", "su", "per", "tra", "fra", "e", "ed", "o", "od", "ma", "se",
    "come", "che", "chi", "non", "più", "del", "dello", "della", "dei",
    "delle", "degli", "al", "allo", "alla", "ai", "agli", "alle", "dal",
    "dallo", "dalla", "dai", "dagli", "dalle", "nel", "nello", "nella",
    "nei", "negli", "nelle", "sul", "sullo", "sulla", "sui", "sugli",
    "sulle", "col", "cui", "questo", "questa", "questi", "queste", "quello",
    "quella", "quelli", "quelle", "sono", "essere", "ha", "hanno", "viene",
    "vengono", "può", "possono", "deve", "devono", "si", "no", "anche",
    "molto", "più", "dove", "quando", "perché", "quindi", "ossia", "cioè",
    # inglese
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "have", "has", "had", "with",
    "by", "from", "this", "that", "these", "those", "it", "its", "as", "at",
    "not", "can", "may", "must", "will", "shall", "into", "onto", "via",
})


class GraphBuilder:
    """Costruisce il Knowledge Graph dalla documentazione."""

    def __init__(self):
        self.graph_file = settings.GRAPH_FILE

    def _load_graph(self) -> dict:
        """Carica il grafo dal disco — fonte di verità condivisa API/worker.

        Nessuna cache in memoria: API e worker sono processi separati e il
        rebuild può azzerare il file mentre il worker estrae. Rileggere a
        ogni accesso evita di resuscitare entità non più corrette da uno
        stato stantio (nodi di documenti eliminati o di dataset precedenti).
        """
        if self.graph_file.exists():
            try:
                return json.loads(self.graph_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {"nodes": [], "edges": []}

    def _save_graph(self, graph: dict):
        """Salva il grafo su disco."""
        self.graph_file.parent.mkdir(parents=True, exist_ok=True)
        self.graph_file.write_text(
            json.dumps(graph, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def reset(self):
        """Azzera completamente il grafo (file su disco).

        Usato dal rebuild per rigenerare il grafo a runtime SOLO dalle
        entità estratte dai documenti correnti: elimina eventuali residui
        stagni (nodi di documenti eliminati o di dataset precedenti) che
        referenziano entità non più corrette.
        """
        if self.graph_file.exists():
            self.graph_file.unlink()

    async def extract_from_document(self, doc_id: str, text: str, title: str,
                                    progress_cb=None) -> int:
        """Estrae triple da un documento usando il LLM.

        Le entità sono generate a runtime e ancorate al testo del documento:
        con GRAPH_REQUIRE_GROUNDING attivo una triple viene accettata solo se
        subject e object compaiono testualmente nel documento (nessuna entità
        inventata dal modello).

        Args:
            doc_id: ID del documento.
            text: Testo normalizzato.
            title: Titolo del documento.
            progress_cb: Callback opzionale (done, total) per il progresso.

        Returns:
            Numero di triple estratte.
        """
        graph = self._load_graph()

        # Dividi il testo in segmenti per non superare il contesto
        segments = self._split_for_extraction(text)
        # Testo completo del documento (normalizzato) per il grounding
        corpus = self._normalize_for_grounding(text)

        all_triples = []
        total = len(segments)
        for idx, segment in enumerate(segments):
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
                print(f"[GraphBuilder] Errore estrazione da {doc_id} "
                      f"(segmento {idx + 1}/{total}): {e}")
            if progress_cb:
                try:
                    progress_cb(idx + 1, total)
                except Exception:
                    pass

        # Filtra per confidence e valida l'ancoraggio al testo del documento
        threshold = settings.GRAPH_CONFIDENCE_THRESHOLD
        require_grounding = bool(getattr(settings, "GRAPH_REQUIRE_GROUNDING", True))
        filtered = []
        rejected = 0
        for t in all_triples:
            if t.get("confidence", 0) < threshold:
                continue
            if require_grounding and not (
                self._is_grounded(t["subject"], corpus)
                and self._is_grounded(t["object"], corpus)
            ):
                rejected += 1
                continue
            filtered.append(t)
        if rejected:
            print(f"[GraphBuilder] {doc_id}: {rejected} triple scartate "
                  f"(entità non presente nel testo del documento)")

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

        self._save_graph(graph)
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
        """Parse tollerante della risposta LLM in triple validate.

        Regge a output con testo fuori dal JSON, recinti markdown e
        troncamenti: gli oggetti ricostruibili vengono recuperati uno a uno.
        Ogni etichetta viene normalizzata e VALIDATA; il grounding verbatim
        sul testo completo del documento avviene in extract_from_document.
        """
        payload = self._extract_json_array(response)
        if not payload:
            return []

        valid = []
        seen = set()
        for t in payload:
            if not isinstance(t, dict):
                continue
            subject = self._sanitize_label(t.get("subject"))
            obj = self._sanitize_label(t.get("object"))
            predicate = self._sanitize_label(t.get("predicate"), is_predicate=True)
            if not subject or not obj or not predicate:
                continue
            # Soggetto e oggetto coincidenti non rappresentano una relazione
            if subject.lower() == obj.lower():
                continue
            try:
                confidence = float(t.get("confidence", 0.7))
            except (TypeError, ValueError):
                confidence = 0.7
            confidence = max(0.0, min(1.0, confidence))
            key = (subject.lower(), predicate.lower(), obj.lower())
            if key in seen:
                continue
            seen.add(key)
            valid.append({
                "subject": subject,
                "predicate": predicate,
                "object": obj,
                "subject_type": self._sanitize_type(t.get("subject_type")),
                "object_type": self._sanitize_type(t.get("object_type")),
                "confidence": confidence,
            })
        return valid

    @staticmethod
    def _extract_json_array(response: str) -> Optional[list]:
        """Estrae il primo array JSON dalla risposta del modello.

        Gestisce recinti markdown, testo prima/dopo l'array e output
        troncato (in tal caso recupera i singoli oggetti riconoscibili).
        """
        if not isinstance(response, str) or not response.strip():
            return None
        text = response.strip()

        candidates = re.findall(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        start = text.find("[")
        if start != -1:
            candidates.append(text[start:text.rfind("]") + 1])

        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                continue

        # Salvataggio per output troncato/malformato: oggetti validi sparsi
        region = text[start:] if start != -1 else text
        objects = []
        for match in re.finditer(r"\{[^{}]*\}", region, re.DOTALL):
            try:
                obj = json.loads(match.group())
                if isinstance(obj, dict):
                    objects.append(obj)
            except json.JSONDecodeError:
                continue
        return objects or None

    def _sanitize_label(self, value, is_predicate: bool = False) -> Optional[str]:
        """Normalizza e valida un'etichetta proveniente dal LLM.

        Rimuove residui di sintassi JSON/markdown, spazi ridondanti e
        punteggiatura ai bordi; scarta segnaposto, etichette eccessivamente
        lunghe e composizioni di sole parole funzionali. Per i predicati la
        validazione è più permissiva (verbi brevi come "è" sono legittimi).
        """
        if not isinstance(value, str):
            return None
        cleaned = value.strip().strip("\"'`«»“”‘’").strip()
        cleaned = re.sub(r"[\[\]{}]", "", cleaned)          # residui JSON
        cleaned = re.sub(r"\s+", " ", cleaned).strip()      # spazi interni
        cleaned = cleaned.strip(" .;:,!?–—|/\\").strip()    # punteggiatura bordo
        min_len = 1 if is_predicate else 2
        if not self._valid_entity_label(cleaned, min_len=min_len):
            return None
        max_len = int(getattr(settings, "GRAPH_MAX_ENTITY_CHARS", 60))
        if len(cleaned) > max_len:
            return None
        tokens = re.findall(r"[\wà-ÿ]+", cleaned, re.IGNORECASE)
        if not is_predicate and tokens and \
                all(tok.lower() in _STOPWORD_TOKENS for tok in tokens):
            return None
        return cleaned

    @staticmethod
    def _sanitize_type(value) -> str:
        """Normalizza il tipo libero descritto dal LLM (nessuna tassonomia)."""
        if not isinstance(value, str):
            return "Non classificato"
        cleaned = re.sub(r"\s+", " ", value.strip()).strip(" .;:,!?")
        if not cleaned or len(cleaned) > 60:
            return "Non classificato"
        return cleaned

    @staticmethod
    def _normalize_for_grounding(text: str) -> str:
        """Normalizza il testo per il confronto verbatim (grounding)."""
        text = text.lower().replace("\u2019", "'").replace("\u2018", "'")
        text = text.replace("\u00a0", " ")
        return re.sub(r"\s+", " ", text)

    def _is_grounded(self, label: str, corpus: str) -> bool:
        """True se l'etichetta compare testualmente nel documento.

        Confronto su testo normalizzato (minuscole, spazi collassati,
        apostrofi uniformati): garantisce che il grafo referenzi solo
        entità realmente presenti nei contenuti, generate a runtime.
        """
        needle = self._normalize_for_grounding(label).strip()
        if not needle:
            return False
        return needle in corpus

    @staticmethod
    def _valid_entity_label(label, min_len: int = 2) -> bool:
        """True se l'etichetta è una denominazione plausibile di entità.

        Controllo puramente strutturale (lunghezza, contenuto, segnaposto
        dell'esempio del prompt): nessun dominio o categoria è predefinito.
        """
        if not isinstance(label, str):
            return False
        cleaned = label.strip()
        if len(cleaned) < min_len or len(cleaned) > 80:
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

        self._save_graph(graph)

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