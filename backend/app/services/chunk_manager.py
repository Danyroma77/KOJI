"""
Chunk Manager — Segmenta testo in chunk con overlap,
rispettando i confini semantici di paragrafi e frasi.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional

from app.config import settings


@dataclass
class Chunk:
    """Singolo chunk di testo con metadati di posizione."""
    text: str
    index: int
    start_char: int
    end_char: int
    doc_id: str
    metadata: dict = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        """Stima approssimativa del numero di token (~4 caratteri per token per l'italiano)."""
        return len(self.text) // 4


class ChunkManager:
    """Segmenta testo normalizzato in chunk configurabili."""

    def __init__(
        self,
        chunk_size: int = None,
        overlap_tokens: int = None,
        respect_boundaries: bool = True,
    ):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.overlap_tokens = overlap_tokens or settings.chunk_overlap_tokens
        self.respect_boundaries = respect_boundaries

    def chunk_text(self, text: str, doc_id: str) -> list[Chunk]:
        """Segmenta il testo in chunk.

        Args:
            text: Testo normalizzato in Markdown.
            doc_id: Identificatore del documento padre.

        Returns:
            Lista di Chunk ordinati per posizione.
        """
        if not text or not text.strip():
            return []

        # Dividi in paragrafi
        paragraphs = self._split_paragraphs(text)

        if self.respect_boundaries:
            chunks = self._chunk_with_boundaries(paragraphs, doc_id)
        else:
            chunks = self._chunk_raw(text, doc_id)

        # Assegna indici
        for i, chunk in enumerate(chunks):
            chunk.index = i

        return chunks

    def _split_paragraphs(self, text: str) -> list[dict]:
        """Divide il testo in paragrafi preservando tipo e posizione."""
        blocks = re.split(r"\n{2,}", text)
        result = []
        char_offset = 0

        for block in blocks:
            stripped = block.strip()
            if not stripped:
                char_offset += len(block) + 2
                continue

            # Identifica il tipo di blocco
            is_heading = bool(re.match(r"^#{1,6}\s", stripped))
            is_list = bool(re.match(r"^[\-\*\d\)]", stripped))
            is_table = "|" in stripped and stripped.count("|") >= 2

            result.append({
                "text": stripped,
                "start": char_offset,
                "end": char_offset + len(stripped),
                "is_heading": is_heading,
                "is_list": is_list,
                "is_table": is_table,
            })
            char_offset += len(block) + 2

        return result

    def _chunk_with_boundaries(self, paragraphs: list[dict], doc_id: str) -> list[Chunk]:
        """Chunking che rispetta i confini di paragrafo."""
        chunks = []
        current_text = ""
        current_start = 0
        current_tokens = 0
        overlap_text = ""
        overlap_start = 0

        def flush():
            nonlocal current_text, current_start, current_tokens, overlap_text, overlap_start
            if current_text.strip():
                chunks.append(Chunk(
                    text=current_text.strip(),
                    index=0,
                    start_char=current_start,
                    end_char=current_start + len(current_text),
                    doc_id=doc_id,
                ))
                # Mantieni ultimi paragrafi come overlap
                overlap_paragraphs = self._get_overlap_tail(current_text)
                overlap_text = "\n\n".join(overlap_paragraphs)
                if overlap_text:
                    # Trova posizione dell'overlap nel testo corrente
                    idx = current_text.rfind(overlap_paragraphs[0] if overlap_paragraphs else "")
                    overlap_start = current_start + max(0, idx)
                else:
                    overlap_start = current_start
            current_text = ""
            current_tokens = 0

        for para in paragraphs:
            para_text = para["text"]
            para_tokens = len(para_text) // 4

            # I titoli iniziano sempre un nuovo chunk
            if para["is_heading"] and current_text:
                flush()
                current_text = para_text
                current_start = para["start"]
                current_tokens = para_tokens
                continue

            # Le tabelle non vengono spezzate
            if para["is_table"] and current_tokens + para_tokens > self.chunk_size:
                flush()
                current_text = para_text
                current_start = para["start"]
                current_tokens = para_tokens
                continue

            # Se aggiungere questo paragrafo supera la dimensione, flush
            if current_tokens + para_tokens > self.chunk_size and current_text:
                flush()
                # Aggiungi overlap
                if overlap_text:
                    current_text = overlap_text + "\n\n" + para_text
                    current_start = overlap_start
                    current_tokens = len(current_text) // 4
                else:
                    current_text = para_text
                    current_start = para["start"]
                    current_tokens = para_tokens
            else:
                if not current_text:
                    current_text = para_text
                    current_start = para["start"]
                else:
                    current_text += "\n\n" + para_text
                current_tokens = len(current_text) // 4

        # Flush finale
        flush()

        return chunks

    def _chunk_raw(self, text: str, doc_id: str) -> list[Chunk]:
        """Chunking grezzo senza rispetto dei confini (fallback)."""
        chars_per_chunk = self.chunk_size * 4  # stima approssimativa
        overlap_chars = self.overlap_tokens * 4

        chunks = []
        i = 0
        idx = 0
        while i < len(text):
            end = min(i + chars_per_chunk, len(text))
            chunk_text = text[i:end].strip()
            if chunk_text:
                chunks.append(Chunk(
                    text=chunk_text,
                    index=0,
                    start_char=i,
                    end_char=end,
                    doc_id=doc_id,
                ))
            i = end - overlap_chars
            idx += 1

        return chunks

    def _get_overlap_tail(self, text: str) -> list[str]:
        """Estrae gli ultimi paragrafi per l'overlap."""
        paragraphs = text.split("\n\n")
        # Tieni paragrafi finché non superi l'overlap
        result = []
        total_chars = 0
        target_chars = self.overlap_tokens * 4

        for para in reversed(paragraphs):
            if total_chars + len(para) > target_chars and result:
                break
            result.insert(0, para)
            total_chars += len(para)

        return result


# Istanza singleton
chunk_manager = ChunkManager()