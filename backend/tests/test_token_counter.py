"""
Test mirati per il TokenCounter (FASE 2B.1).

Verifica che il conteggio dei token sia REALE (tokenizer WordPiece del modello
di embedding all-MiniLM-L6-v2), deterministico, e che le primitive esposte
(encode/tokenize/offsets) siano coerenti. NON copre ancora la strategia TOKEN
completa (500/1000/1500). Da eseguire DENTRO il container backend:
    docker compose exec koji-api python -m pytest tests/test_token_counter.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

import pytest  # noqa: E402

from app.services.token_counter import (  # noqa: E402
    TokenCounter,
    token_counter,
    resolve_hf_name,
)
from app.services.chunk_manager import Chunk  # noqa: E402


@pytest.fixture(scope="module")
def counter() -> TokenCounter:
    c = TokenCounter()  # usa settings.EMBEDDING_MODEL corrente
    c.force_load()
    return c


# ---------------------------------------------------------------------------
# 1. Risoluzione alias
# ---------------------------------------------------------------------------


class TestResolution:
    def test_alias_no_slash(self):
        assert resolve_hf_name("all-MiniLM-L6-v2") == (
            "sentence-transformers/all-MiniLM-L6-v2"
        )

    def test_models_with_slash_unchanged(self):
        assert resolve_hf_name("BAAI/bge-small-en") == "BAAI/bge-small-en"
# ---------------------------------------------------------------------------
# 3. Casi di testo richiesti
# ---------------------------------------------------------------------------


class TestCountTokens:
    SHORT_IT = "Ciao mondo."
    PUNCT = "Un, punto? Due; virgole: tre! Punti... virgolette \"x\" e parentesi (y)."
    NUMBERS = "Totale 123, sconto 3.14159%, codice X9K-42: prezzo 10 e 200 elementi."
    LIST = "- primo elemento\n* secondo elemento\n1. terzo con numerazione\n- quarto (finale)"
    EMPTY = ""
    LONG = ("Questa è una frase di prova. " * 400)  # ~ 10k caratteri

    def test_short_italian(self, counter):
        n = counter.count_tokens(self.SHORT_IT)
        assert n > 0
        assert n == len(counter.encode(self.SHORT_IT))

    def test_punctuation(self, counter):
        n = counter.count_tokens(self.PUNCT)
        assert n > 0
        assert len(counter.encode(self.PUNCT)) == len(counter.tokenize(self.PUNCT))

    def test_numbers(self, counter):
        assert counter.count_tokens(self.NUMBERS) > 0
        assert "123" in counter.tokenize("53 123 42")

    def test_lists(self, counter):
        assert counter.count_tokens(self.LIST) > 0
        assert counter.count_tokens("-") == 1

    def test_empty(self, counter):
        assert counter.count_tokens(self.EMPTY) == 0
        assert counter.encode(self.EMPTY) == []
        assert counter.tokenize(self.EMPTY) == []
        assert counter.token_offsets(self.EMPTY) == []

    def test_long_text(self, counter):
        n = counter.count_tokens(self.LONG)
        assert n > 500
        assert n == len(counter.encode(self.LONG))

    def test_deterministic_repeated(self, counter):
        text = self.PUNCT + "\n" + self.LIST
        assert counter.count_tokens(text) == counter.count_tokens(text)


# ---------------------------------------------------------------------------
# 4. Mapping token -> testo (offsets) e conteggio
# ---------------------------------------------------------------------------


class TestOffsets:
    def test_offsets_length_matches_tokens(self, counter):
        text = "Ciao mondo. Questo è un test, 123 e - elenco."
        offsets = counter.token_offsets(text)
        assert len(offsets) == counter.count_tokens(text)

    def test_offsets_are_sorted_and_within_bounds(self, counter):
        text = "Punteggiatura! Numeri 42 e liste: - uno - due."
        prev_end = 0
        for s, e in counter.token_offsets(text):
            assert 0 <= s <= e <= len(text)
            assert s >= prev_end
            prev_end = e

    def test_reassemble_from_offsets(self, counter):
        text = "Minuscole e MAIUSCOLE mista."
        offsets = counter.token_offsets(text)
        chars = "".join(text[s:e] for s, e in offsets)
        # WordPiece può scartare spazi, mai aggiungere caratteri.
# ---------------------------------------------------------------------------
# 2bis. Tokenizer reale: tipo, alias singleton e determinismo
# ---------------------------------------------------------------------------


class TestTokenizerIdentity:
    def test_is_bert_fast_tokenizer(self, counter):
        # all-MiniLM-L6-v2 usa WordPiece -> BertTokenizerFast.
        assert counter.tokenizer.__class__.__name__ == "BertTokenizerFast"

    def test_singleton_resolves_embedding_model(self):
        assert token_counter.model_name == resolve_hf_name("all-MiniLM-L6-v2")

    def test_encoding_is_deterministic(self, counter):
        text = "Giuseppe Verdi compose la Traviata nel 1853."
        assert counter.encode(text) == counter.encode(text)
        assert counter.count_tokens(text) == counter.count_tokens(text)
        assert len(chars) >= len(text)


# ---------------------------------------------------------------------------
# 5. Integrazione con Chunk.token_estimate
# ---------------------------------------------------------------------------


class TestChunkTokenEstimate:
    def test_token_estimate_uses_real_counter(self, counter):
        text = "Questo è un chunk di test con conteggio reale."
        chunk = Chunk(text=text, index=0, start_char=0, end_char=len(text), doc_id="d1")
        assert chunk.token_estimate == counter.count_tokens(text)

    def test_not_naive_chars4(self, counter):
        # Il conteggio reale NON coincide con la vecchia stima len(text) // 4.
        text = "ciao mondo, questo e' un testo con punteggiatura e numeri 123 su un chunk."
        chunk = Chunk(text=text, index=0, start_char=0, end_char=len(text), doc_id="d1")
        assert chunk.token_estimate != len(text) // 4
        assert chunk.token_estimate == counter.count_tokens(text)

    def test_singleton_resolves_embedding_model(self):
        assert token_counter.model_name == resolve_hf_name("all-MiniLM-L6-v2")


# ---------------------------------------------------------------------------
# 2. Tokenizer reale: tipo e determinismo
# ---------------------------------------------------------------------------


class TestTokenizerIdentity:
    def test_is_bert_fast_tokenizer(self, counter):
        # all-MiniLM-L6-v2 usa WordPiece -> BertTokenizerFast.
        assert counter.tokenizer.__class__.__name__ == "BertTokenizerFast"

    def test_encoding_is_deterministic(self, counter):
        text = "Giuseppe Verdi compose la Traviata nel 1853."
        assert counter.encode(text) == counter.encode(text)
        assert counter.count_tokens(text) == counter.count_tokens(text)