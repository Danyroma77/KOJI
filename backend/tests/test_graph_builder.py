"""
Test funzionali per GraphBuilder.

Verifica le unità di logica in isolamento con LLM mock:
- parsing delle risposte LLM (tollerante)
- sanitizzazione label
- grounding (corrispondenza testuale)
- deduplicazione nodi (Jaccard + slug)
- estrazione end-to-end da documento
- rimozione per documento
- reset e persistenza

Usa grafi temporanei su filesystem per non alterare lo stato
della piattaforma; il grafo su disco è isolato per ogni test.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

import pytest
from unittest.mock import AsyncMock, patch

# Permette import assoluti "app.*" lanciando pytest dalla root del repo.
_SRC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SRC_ROOT / "backend"))

from app.config import settings
from app.services.graph_builder import (
    GraphBuilder,
    GRAPH_DEDUP_SIMILARITY_THRESHOLD,
)

try:
    from app.services import llm_manager as _llm_mod
except Exception:
    _llm_mod = None  # pragma: no cover - fallback se il modulo non è importabile


# =============================================================================
# Fixture
# =============================================================================

@pytest.fixture
def tmp_graph_path(tmp_path: Path) -> Path:
    """Path per un graph.json isolato sul filesystem temporaneo."""
    return tmp_path / "graph.json"


@pytest.fixture
def graph_builder(tmp_graph_path: Path) -> GraphBuilder:
    """GraphBuilder con self.graph_file = tmp_graph_path.

    Per non modificare le settings globali, l'istanza usa un path
    sovrascritto dopo la costruzione (più semplice e affidabile dei
    monkeypatch del config).
    """
    gb = GraphBuilder()
    gb.graph_file = tmp_graph_path
    return gb


@pytest.fixture
def llm_generator() -> Callable[[list[dict]], AsyncMock]:
    """Restituisce un mock AsyncMock di llm_manager.generate calibrato su
    una lista di triple (che verranno serializzate in JSON).

    Uso tipico::

        gen = llm_generator()
        gen([_triple(...)])
        with patch("app.services.graph_builder.llm_manager.generate", gen):
            ...
    """

    async def maker(triples: list[dict], /) -> str:
        payload = json.dumps(triples, ensure_ascii=False)
        return {
            "response": payload,
            "tokens_per_second": 42.0,
            "error": None,
        }

    mock = AsyncMock(side_effect=maker)
    return mock


def _triple(
    subject: str,
    predicate: str,
    object_: str,
    subject_type: str = "Entità",
    object_type: str = "Entità",
    confidence: float = 0.9,
) -> dict:
    return {
        "subject": subject,
        "predicate": predicate,
        "object": object_,
        "subject_type": subject_type,
        "object_type": object_type,
        "confidence": confidence,
    }


def triples_to_json(triples: list[dict]) -> str:
    """Serializza una lista di triple in un JSON array compatibile col prompt."""
    return json.dumps(triples, ensure_ascii=False)


def mock_llm_responses(*responses: str) -> AsyncMock:
    """Restituisce un AsyncMock che produce le risposte passate in sequenza.

    Ogni *response* è il valore che l'LLM dovrebbe restituire (es. un JSON).
    Se non viene chiamato generate con il numero esatto, il mock solleva
    AssertionError al termine del test (via side_effect esaurimento).
    """
    mock = AsyncMock()
    mock.generate = AsyncMock(side_effect=list(responses))
    return mock


def _patch_llm(responses: list[str]):
    """Context-manager estilo: patcha llm_manager.generate con le risposte."""
    mock = AsyncMock()
    mock.generate = AsyncMock(side_effect=list(responses))
    return patch("app.services.graph_builder.llm_manager", mock)

    """Verifica la tolleranza del parser alle risposte LLM reali."""

    # ---------------------------------------------------------------------------
    # JSON valido
    # ---------------------------------------------------------------------------
    def test_parse_json_array(self, graph_builder: GraphBuilder):
        resp = json.dumps([
            _triple("A", "legato", "B"),
            _triple("B", "collegato", "C"),
        ])
        out = graph_builder._parse_response(resp)
        assert len(out) == 2
        assert out[0]["subject"] == "A"
        assert out[1]["predicate"] == "collegato"

    # ---------------------------------------------------------------------------
    # JSON avvolto in markdown fence / testo
    # ---------------------------------------------------------------------------
    def test_parse_json_in_markdown_fence(self, graph_builder: GraphBuilder):
        body = json.dumps([_triple("Redis", "è", "cache")])
        resp = "```json\n" + body + "\n```"
        out = graph_builder._parse_response(resp)
        assert len(out) == 1

    def test_parse_json_with_pretext(self, graph_builder: GraphBuilder):
        body = json.dumps([_triple("Kafka", "gestisce", "messaggi")])
        resp = "# Estrazione\n" + body + "\nFINE"
        out = graph_builder._parse_response(resp)
        assert len(out) == 1
        assert out[0]["subject"] == "Kafka"

    # ---------------------------------------------------------------------------
    # Risposte malformate / recovery
    # ---------------------------------------------------------------------------
    def test_empty_string(self, graph_builder: GraphBuilder):
        assert graph_builder._parse_response("") == []

    def test_whitespace_only(self, graph_builder: GraphBuilder):
        assert graph_builder._parse_response("   \n  ") == []

    def test_none(self, graph_builder: GraphBuilder):
        assert graph_builder._parse_response(None) == []

    def test_json_unclosed_array_recovers_single_object(self, graph_builder: GraphBuilder):
        """Array aperto ma non chiuso: il parser dovrebbe recuperare l'oggetto
        singolo riconoscibile."""
        resp = '[{"subject": "X", "predicate": "z", "object": "Y"}'  # mancante ]
        out = graph_builder._parse_response(resp)
        assert len(out) == 1
        assert out[0]["subject"] == "X"

    def test_pure_text_no_json(self, graph_builder: GraphBuilder):
        assert graph_builder._parse_response(
            "Non ci sono relazioni significative nel documento."
        ) == []

    def test_text_only_no_json_but_with_curly_braces(self, graph_builder: GraphBuilder):
        assert graph_builder._parse_response("La risposta è {qualcosa}") == []

    # ---------------------------------------------------------------------------
    # Filtri semantici interni al parser
    # ---------------------------------------------------------------------------
    # ---------------------------------------------------------------------------
    # Preferenze linguistiche del parser
    # ---------------------------------------------------------------------------
    def test_multiple_spaces_normalized(self, graph_builder: GraphBuilder):
        body = json.dumps([_triple("Microsoft   Azure", "z", "Cloud")])
        out = graph_builder._parse_response(body)
        assert out[0]["subject"] == "Microsoft Azure"

    def test_subject_equal_object_excluded(self, graph_builder: GraphBuilder):
        resp = json.dumps([_triple("X", "è", "X")])
        out = graph_builder._parse_response(resp)
        assert out == []

    def test_invalid_label_scartata(self, graph_builder: GraphBuilder):
        resp = json.dumps([_triple("subject", "z", "B")])
        out = graph_builder._parse_response(resp)
        assert out == []  # "subject" è in _INVALID_LABELS

    def test_confidence_default_to_07_when_missing(self, graph_builder: GraphBuilder):
        resp = json.dumps([{
            "subject": "A", "predicate": "z", "object": "B",
            "subject_type": "Entità", "object_type": "Entità",
        }])
        out = graph_builder._parse_response(resp)
        assert out[0]["confidence"] == 0.7

    def test_confidence_clamped_to_0_1(self, graph_builder: GraphBuilder):
        resp = json.dumps([
            _triple("A", "z", "B", confidence=1.5),
            _triple("C", "z", "D", confidence=-0.3),
        ])
        out = graph_builder._parse_response(resp)
        assert out[0]["confidence"] == pytest.approx(1.0)
        assert out[1]["confidence"] == pytest.approx(0.0)
class TestIsGrounded:
    """Verifica la corrispondenza testuale (grounding) delle label nel corpus."""

    # ---------------------------------------------------------------------------
    # Casi positivi
    # ---------------------------------------------------------------------------
    def test_entity_present(self, graph_builder: GraphBuilder):
        corpus = graph_builder._normalize_for_grounding("Il sistema usa Microsoft.")
        assert graph_builder._is_grounded("Microsoft", corpus) is True

    def test_entity_case_insensitive(self, graph_builder: GraphBuilder):
        corpus = graph_builder._normalize_for_grounding("MICROSOFT è usato.")
        assert graph_builder._is_grounded("Microsoft", corpus) is True

    def test_apostrophe_normalized_in_corpus(self, graph_builder: GraphBuilder):
        corpus = graph_builder._normalize_for_grounding(
            "L\u2019azienda ha sviluppato il prodotto."
        )
        assert graph_builder._is_grounded("L'azienda", corpus) is True
        assert graph_builder._is_grounded("L\u2019azienda", corpus) is True

    def test_multiple_spaces_collapsed(self, graph_builder: GraphBuilder):
        corpus = graph_builder._normalize_for_grounding("Microsoft    Azure")
        assert graph_builder._is_grounded("Microsoft Azure", corpus) is True

    def test_non_breaking_space(self, graph_builder: GraphBuilder):
        corpus = graph_builder._normalize_for_grounding("Microsoft\u00a0Azure")
        assert graph_builder._is_grounded("Microsoft Azure", corpus) is True

    def test_entity_with_internal_punctuation(self, graph_builder: GraphBuilder):
        corpus = graph_builder._normalize_for_grounding(
            "Consultare Art. 5 del regolamento."
        )
        assert graph_builder._is_grounded("Art. 5", corpus) is True

    # ---------------------------------------------------------------------------
class TestSimilarity:
    """Verifica il calcolo di similarità (Jaccard su token)."""

    def test_identical(self, graph_builder: GraphBuilder):
        assert graph_builder._similarity("A B C", "A B C") == pytest.approx(1.0)

    def test_disjoint(self, graph_builder: GraphBuilder):
        assert graph_builder._similarity("A B", "C D") == pytest.approx(0.0)

    def test_partial_overlap(self, graph_builder: GraphBuilder):
        # {"a","b"} vs {"b","c"} → intersection 1, union 3 → 1/3
        assert graph_builder._similarity("A B", "B C") == pytest.approx(1 / 3)

    def test_case_insensitive(self, graph_builder: GraphBuilder):
        assert graph_builder._similarity("A B", "a b") == pytest.approx(1.0)

    def test_single_word_identical(self, graph_builder: GraphBuilder):
        assert graph_builder._similarity("Microsoft", "Microsoft") == pytest.approx(1.0)

    def test_single_word_different(self, graph_builder: GraphBuilder):
        assert graph_builder._similarity("Apple", "Oracle") == pytest.approx(0.0)

    def test_empty_string_returns_zero(self, graph_builder: GraphBuilder):
        assert graph_builder._similarity("", "A") == pytest.approx(0.0)
        assert graph_builder._similarity("A", "") == pytest.approx(0.0)
        assert graph_builder._similarity("", "") == pytest.approx(0.0)

    def test_threshold_092_boundary(self, graph_builder: GraphBuilder):
        # Jaccard = 0.9 è < 0.92 → nodi separati
        # Jaccard = 0.93 è >= 0.92 → nodi fusi

        # 2 parole identiche + 1 diversa vs 2 identiche → Jaccard = 2/3 = 0.666
        # Per ottenere 0.9 usiamo 10 token identici + 1 diverso vs 10 identici
        # Jaccard = 10/11 = 0.909 < 0.92
        words1 = " ".join(str(i) for i in range(10))
        words2 = " ".join(str(i) for i in range(9)) + "X"
        sim = graph_builder._similarity(words1, words2)
        assert sim < GRAPH_DEDUP_SIMILARITY_THRESHOLD
        assert sim == pytest.approx(10 / 11)

        # 10 identici + 0 diversi → 1.0
        words3 = " ".join(str(i) for i in range(10))
        assert graph_builder._similarity(words1, words3) == pytest.approx(1.0)

    # Casi negativi
    # ---------------------------------------------------------------------------
    def test_entity_absent(self, graph_builder: GraphBuilder):
        corpus = graph_builder._normalize_for_grounding("Oracle è usato.")
        assert graph_builder._is_grounded("Microsoft", corpus) is False

class TestSlugify:
    """Verifica la conversione label → ID slug."""

    def test_lowercase(self, graph_builder: GraphBuilder):
        assert graph_builder._slugify("Microsoft") == "microsoft"

    def test_accented_characters_normalized(self, graph_builder: GraphBuilder):
        assert graph_builder._slugify("Caffè") == "caffe"
        assert graph_builder._slugify("Perché") == "perche"
        assert graph_builder._slugify("Àngelo") == "angelo"

    def test_non_alphanumeric_replaced(self, graph_builder: GraphBuilder):
        assert graph_builder._slugify("C++") == "c"
        assert graph_builder._slugify("Node.js") == "node_js"
        assert graph_builder._slugify("A&B") == "a_b"

    def test_truncated_to_40_chars(self, graph_builder: GraphBuilder):
        slug = graph_builder._slugify("A" * 60)
        assert len(slug) == 40
        assert slug == "a" * 40

    def test_strips_leading_trailing_underscores(self, graph_builder: GraphBuilder):
        assert graph_builder._slugify("  --A--  ") == "a"

    def test_only_symbols_defaults_to_node(self, graph_builder: GraphBuilder):
        assert graph_builder._slugify("!@#$%") == "node"

    def test_slug_uniqueness_with_collision(self, graph_builder: GraphBuilder):
        # Due label che slugificano allo stesso ID
        # "C" e "C++" → entrambi slug "c"
        id1 = graph_builder._slugify("C")
        id2 = graph_builder._slugify("C++")
        assert id1 == id2 == "c"


class TestAddNode:
    """Verifica creazione, riutilizzo e fusione di nodi."""

    def test_new_node_created(self, graph_builder: GraphBuilder):
        graph = {"nodes": [], "edges": []}
        node = graph_builder._add_node(graph, "Microsoft", "Software", "doc1")
        assert node["label"] == "Microsoft"
        assert node["type"] == "Software"
        assert node["documents"] == ["doc1"]
        assert len(graph["nodes"]) == 1

    def test_existing_node_reused(self, graph_builder: GraphBuilder):
        graph = {"nodes": [], "edges": []}
        n1 = graph_builder._add_node(graph, "Microsoft", "Software", "doc1")
        n2 = graph_builder._add_node(graph, "Microsoft", "Cloud", "doc2")
        assert n1["id"] == n2["id"]
        assert n2["documents"] == ["doc1", "doc2"]
        assert n2["type"] == "Software"

    def test_similar_node_merged(self, graph_builder: GraphBuilder):
        graph = {"nodes": [], "edges": []}
        # "Microsoft" vs "Microsoft" → Jaccard 1.0
        n1 = graph_builder._add_node(graph, "Microsoft", "Software", "doc1")
        n2 = graph_builder._add_node(graph, "Microsoft", "Cloud", "doc2")
        assert n1["id"] == n2["id"]
        assert len(graph["nodes"]) == 1
        assert n2["documents"] == ["doc1", "doc2"]

    def test_similar_order_invariant(self, graph_builder: GraphBuilder):
        """Ordine diverso delle parole → Jaccard 1.0 → fuso."""
        graph = {"nodes": [], "edges": []}
        graph_builder._add_node(graph, "Antonio Rossi", "Persona", "doc1")
        n2 = graph_builder._add_node(graph, "Rossi Antonio", "Persona", "doc2")
        assert len(graph["nodes"]) == 1
        assert n2["documents"] == ["doc1", "doc2"]

    def test_not_similar_creates_separate_node(self, graph_builder: GraphBuilder):
        graph = {"nodes": [], "edges": []}
        graph_builder._add_node(graph, "Apple", "Azienda", "doc1")
        n2 = graph_builder._add_node(graph, "Apple Computer", "Azienda", "doc2")
        assert len(graph["nodes"]) == 2
        assert {n["label"] for n in graph["nodes"]} == {"Apple", "Apple Computer"}

    def test_slug_collision_suffix(self, graph_builder: GraphBuilder):
        graph = {"nodes": [], "edges": []}
        n1 = graph_builder._add_node(graph, "C", "Linguaggio", "doc1")
        n2 = graph_builder._add_node(graph, "C++", "Linguaggio", "doc2")
        assert n1["id"] == "c"
        assert n2["id"] == "c_1"
        assert len(graph["nodes"]) == 2

    def test_type_default_when_empty(self, graph_builder: GraphBuilder):
        graph = {"nodes": [], "edges": []}
        node = graph_builder._add_node(graph, "A", "", "doc1")
        assert node["type"] == "Non classificato"

    def test_documents_list_initialized(self, graph_builder: GraphBuilder):
        graph = {"nodes": [], "edges": []}
        node = graph_builder._add_node(graph, "A", "T", "d1")
        assert "documents" in node
        assert isinstance(node["documents"], list)

    def test_empty_label_not_grounded(self, graph_builder: GraphBuilder):
        corpus = graph_builder._normalize_for_grounding("qualcosa")
        assert graph_builder._is_grounded("", corpus) is False
        assert graph_builder._is_grounded("   ", corpus) is False

    # ---------------------------------------------------------------------------
    # Gap documentato: ordine inverso / punteggiatura
    # ---------------------------------------------------------------------------
    def test_order_inverted_with_comma_is_false_negative(self, graph_builder: GraphBuilder):
        """ORDINE INVERSO CON VIRGOLA: needle "Antonio Rossi" non è grounded
        nel corpus "...Rossi, Antonio..." perché il grounding è substring esatto.

        Questo è un gap noto (vedi analisi gap documentazione). Il test documenta
        il comportamento attuale senza pretensione di fix: serve a non regressare
        e a segnalare il caso per un futuro miglioramento (es. matching token-based
        o normalizzazione dell'ordine).
        """
        corpus = graph_builder._normalize_for_grounding(
            "Il responsabile Rossi, Antonio ha firmato il documento."
        )
        # Atteso: False (falso negativo noto)
        assert graph_builder._is_grounded("Antonio Rossi", corpus) is False
        # Gli elementi singoli sono grounded
        assert graph_builder._is_grounded("Rossi", corpus) is True
        assert graph_builder._is_grounded("Antonio", corpus) is True

    def test_plurale_form_different_from_singular_false_negative(self, graph_builder: GraphBuilder):
        """Grounding esatto: plurale "servizi" non è grounded nel testo singolare
        "il servizio". Gap noto (substring esatto, nessuna lemmatizzazione)."""
        corpus = graph_builder._normalize_for_grounding("Il servizio è attivo.")
        assert graph_builder._is_grounded("servizi", corpus) is False
        assert graph_builder._is_grounded("servizio", corpus) is True

    def test_hyphen_vs_space_false_negative(self, graph_builder: GraphBuilder):
        """Graph DB (spazio) non è grounded in "graph-db" (trattino)."""
        corpus = graph_builder._normalize_for_grounding("usiamo graph-db")
        assert graph_builder._is_grounded("Graph DB", corpus) is False


    def test_predicate_less_than_one_word_rejected(self, graph_builder: GraphBuilder):
        """Un predicato di zero parole (stringa vuota o solo spazi) è scartato."""
        resp = json.dumps([_triple("A", "   ", "B")])
        out = graph_builder._parse_response(resp)
        assert out == []

    def test_subject_type_and_object_type_preserved(self, graph_builder: GraphBuilder):
        resp = json.dumps([_triple("A", "z", "B",
                                    subject_type="Persona", object_type="Azienda")])
        out = graph_builder._parse_response(resp)
        assert out[0]["subject_type"] == "Persona"
class TestSanitizeLabel:
    """Verifica la pulizia e validazione delle label provenienti dall'LLM."""

    # ---------------------------------------------------------------------------
    # Pulizia
    # ---------------------------------------------------------------------------
    def test_clean_label_unchanged(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label("Microsoft") == "Microsoft"

    def test_label_with_trailing_punctuation(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label("Microsoft.") == "Microsoft"
        assert graph_builder._sanitize_label("Microsoft,") == "Microsoft"
        assert graph_builder._sanitize_label("Microsoft!") == "Microsoft"

    def test_label_with_json_residue(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label('{"subject"}') is None
        assert graph_builder._sanitize_label('[{ "A" }]') is None

    def test_label_with_md_residue(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label("**Microsoft**") == "Microsoft"

    def test_label_too_long(self, graph_builder: GraphBuilder, monkeypatch):
        monkeypatch.setattr(settings, "GRAPH_MAX_ENTITY_CHARS", 10)
        assert graph_builder._sanitize_label("ABCDEFGHIJKLMNOP") is None
        assert graph_builder._sanitize_label("AB CD") == "AB CD"

    def test_label_with_quotes_stripped(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label('"Microsoft"') == "Microsoft"
        assert graph_builder._sanitize_label("`Sistema`") == "Sistema"
        assert graph_builder._sanitize_label("\u201cTesto\u201d") == "Testo"

    def test_extra_spaces_collapsed(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label("A   B") == "A B"
        assert graph_builder._sanitize_label("  A B  ") == "A B"

    # ---------------------------------------------------------------------------
    # Stopword
    # ---------------------------------------------------------------------------
    def test_stopword_only_label_rejected(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label("il") is None
        assert graph_builder._sanitize_label("the") is None
        assert graph_builder._sanitize_label("di e il") is None

    def test_label_with_stopwords_and_content_accepted(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label("il sistema") == "il sistema"

    # ---------------------------------------------------------------------------
    # Predicati
    # ---------------------------------------------------------------------------
    def test_predicate_short_accepted(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label("è", is_predicate=True) == "è"
        assert graph_builder._sanitize_label("di", is_predicate=True) == "di"

    def test_predicate_min_length_one(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label("a", is_predicate=True) == "a"

    def test_predicate_longer_than_max_chars_rejected(self, graph_builder: GraphBuilder, monkeypatch):
        monkeypatch.setattr(settings, "GRAPH_MAX_ENTITY_CHARS", 5)
        assert graph_builder._sanitize_label("configura sistemi", is_predicate=True) is None
        assert graph_builder._sanitize_label("configura", is_predicate=True) == "configura"

    # ---------------------------------------------------------------------------
    # Placeholder dell'esempio del prompt
    # ---------------------------------------------------------------------------
    def test_invalid_placeholder_labels_rejected(self, graph_builder: GraphBuilder):
        for label in (
            "entità a", "entita a", "entity a",
            "subject", "object", "predicate", "confidence",
            "n/a", "null", "none", "unknown",
            "testo", "text",
        ):
            assert graph_builder._sanitize_label(label) is None, f"{label} doveva essere scartata"

    # ---------------------------------------------------------------------------
    # Input non stringa
    # ---------------------------------------------------------------------------
    def test_non_string_input(self, graph_builder: GraphBuilder):
        assert graph_builder._sanitize_label(None) is None
        assert graph_builder._sanitize_label(123) is None
        assert graph_builder._sanitize_label(["a"]) is None

        assert out[0]["object_type"] == "Azienda"

def _triple(
    subject: str,
    predicate: str,
    object_: str,
    subject_type: str = "Entità",
    object_type: str = "Entità",
    confidence: float = 0.9,
) -> dict:
    return {
        "subject": subject,
        "predicate": predicate,
        "object": object_,
        "subject_type": subject_type,
        "object_type": object_type,
        "confidence": confidence,
    }
