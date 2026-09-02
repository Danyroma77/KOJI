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
        # None = usa il valore CORRENTE di settings a ogni accesso: le
        # modifiche fatte dalla pagina Admin sono effettive immediatamente,
        # senza riavvio di API/worker. Passando un valore esplicito (usato
        # dai benchmark per esperimenti ripetibili) esso ha precedenza.
        self._chunk_size_override = chunk_size
        self._overlap_override = overlap_tokens
        self.respect_boundaries = respect_boundaries

    @property
    def chunk_size(self) -> int:
        """Dimensione target del chunk (token), letta dalla config a ogni uso."""
        return self._chunk_size_override or settings.CHUNK_SIZE

    @property
    def overlap_tokens(self) -> int:
        """Overlap in token, derivato dalla percentuale corrente."""
        return self._overlap_override or settings.chunk_overlap_tokens

    # Alias accettati per la strategia (env/Admin) -> valore interno
    STRATEGY_ALIASES = {
        "paragraph": "paragraph", "paragrafo": "paragraph", "paragrafi": "paragraph",
        "section": "section", "sezione": "section", "sezioni": "section",
        "heading": "section", "markdown": "section",
        "sentence": "sentence", "frase": "sentence", "frasi": "sentence",
        "fixed": "fixed", "fisso": "fixed", "finestra": "fixed",
        "window": "fixed", "raw": "fixed",
        "page": "page", "pagina": "page", "pagine": "page",
    }

    @classmethod
    def normalize_strategy(cls, value) -> str:
        """Normalizza la strategia richiesta; valori ignoti -> paragraph."""
        if not isinstance(value, str) or not value.strip():
            return "paragraph"
        return cls.STRATEGY_ALIASES.get(value.strip().lower(), "paragraph")

    def chunk_text(self, text: str, doc_id: str) -> list[Chunk]:
        """Segmenta il testo in chunk secondo la strategia configurata.

        La strategia (settings.CHUNK_STRATEGY) è letta a ogni chiamata:
        "paragraph" (default), "section", "sentence", "fixed" o "page".

        Args:
            text: Testo normalizzato in Markdown.
            doc_id: Identificatore del documento padre.

        Returns:
            Lista di Chunk ordinati per posizione.
        """
        if not text or not text.strip():
            return []

        strategy = self.normalize_strategy(settings.CHUNK_STRATEGY)

        if strategy == "fixed":
            chunks = self._chunk_raw(text, doc_id)
        elif strategy == "section":
            chunks = self._chunk_by_sections(text, doc_id)
        elif strategy == "sentence":
            chunks = self._chunk_by_sentences(text, doc_id)
        elif strategy == "page":
            chunks = self._chunk_by_pages(text, doc_id)
        else:
            paragraphs = self._split_paragraphs(text)
            chunks = (
                self._chunk_with_boundaries(paragraphs, doc_id)
                if self.respect_boundaries
                else self._chunk_raw(text, doc_id)
            )

        # Assegna indici e traccia la strategia usata (utile per benchmark)
        for i, chunk in enumerate(chunks):
            chunk.index = i
            chunk.metadata["strategy"] = strategy
            chunk.metadata["total_chunks"] = len(chunks)

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

    # ---------- Strategia "section": chunk per sezione Markdown ----------

    def _chunk_by_sections(self, text: str, doc_id: str) -> list[Chunk]:
        """Un chunk per sezione Markdown (ogni titolo H1-H6 apre una sezione).

        Le sezioni entro la dimensione target restano intere (titolo
        incluso); quelle più grandi vengono spezzate ai confini di
        paragrafo — e, per paragrafi singoli oversize, di frase.
        """
        blocks = self._split_paragraphs(text)
        if not blocks:
            return self._chunk_raw(text, doc_id)

        # Raggruppa i blocchi per sezione: ogni heading apre una nuova sezione
        sections: list[list[dict]] = []
        for block in blocks:
            if block["is_heading"] or not sections:
                sections.append([block])
            else:
                sections[-1].append(block)

        chunks = []
        for section in sections:
            section_tokens = sum(len(b["text"]) // 4 for b in section)
            if section_tokens <= self.chunk_size:
                chunks.append(self._make_chunk(section, doc_id))
            else:
                chunks.extend(self._pack_blocks(section, doc_id))
        return chunks

    def _chunk_by_pages(self, text: str, doc_id: str) -> list[Chunk]:
        """Strategia "page": un chunk per pagina del documento originale.

        Il parser PDF inserisce un separatore \\f (form feed) tra i testi di
        pagine diverse. Qui suddividiamo su quel separatore: ogni chunk
        corrisponde esattamente a una pagina del documento originale.

        Pagine vuote vengono scartate. Pagine più grandi di chunk_size token
        vengono suddivise in sotto-chunk rispettando i confini di paragrafo.
        """
        PAGE_BREAK = "\f"
        pages = text.split(PAGE_BREAK)

        chunks = []
        global_offset = 0

        for page_num, page_text in enumerate(pages, start=1):
            page_text = page_text.strip()
            if not page_text:
                continue

            page_start = global_offset
            page_end = global_offset + len(page_text)
            global_offset = page_end + 1  # +1 per il separatore

            page_tokens = len(page_text) // 4

            if page_tokens <= self.chunk_size:
                # La pagina entra in un singolo chunk
                chunks.append(Chunk(
                    text=page_text,
                    index=0,
                    start_char=page_start,
                    end_char=page_end,
                    doc_id=doc_id,
                    metadata={"page": page_num},
                ))
            else:
                # Pagina oversize: suddividi in sotto-chunk per paragrafi
                sub_chunks = self._split_paragraphs(page_text)
                if sub_chunks:
                    packed = self._chunk_with_boundaries(sub_chunks, doc_id)
                    for chunk in packed:
                        chunk.metadata["page"] = page_num
                        chunks.append(chunk)

        return chunks

    @staticmethod
    def _make_chunk(blocks: list[dict], doc_id: str) -> Chunk:
        """Crea un chunk da un gruppo di blocchi adiacenti."""
        return Chunk(
            text="\n\n".join(b["text"] for b in blocks),
            index=0,
            start_char=blocks[0]["start"],
            end_char=blocks[-1]["end"],
            doc_id=doc_id,
        )

    def _pack_blocks(self, blocks: list[dict], doc_id: str) -> list[Chunk]:
        """Confeziona blocchi fino alla dimensione target.

        I paragrafi singoli oversize (esclusi i titoli e le tabelle, che non
        si spezzano) vengono prima suddivisi in frasi.
        """
        units = []
        for block in blocks:
            if len(block["text"]) // 4 > self.chunk_size and \
                    not block["is_table"] and not block["is_heading"]:
                units.extend(self._split_sentences_block(block))
            else:
                units.append(block)
        return self._chunk_with_boundaries(units, doc_id)

    def _split_sentences_block(self, block: dict) -> list[dict]:
        """Suddivide un blocco oversize in unità di frase con offset assoluti."""
        return [
            {
                "text": sent_text,
                "start": s_start,
                "end": s_end,
                "is_heading": False,
                "is_list": block["is_list"],
                "is_table": False,
            }
            for sent_text, s_start, s_end in self._iter_sentences(block["text"], block["start"])
        ]

    # ---------- Strategia "sentence": frasi complete ----------

    # Frase = testo fino a punteggiatura forte, newline o fine testo
    _SENTENCE_RE = re.compile(r"[^.!?…\n]+(?:[.!?…]+|\n|$)")

    # Titolo Markdown (H1-H6): attaccato alla frase successiva in modalità
    # sentence, così nessun chunk termina con un titolo e la coppia
    # titolo+contenuto resta unita nell'unità di retrieval
    _HEADING_RE = re.compile(r"^#{1,6}\s")

    def _iter_sentences(self, text: str, base: int = 0):
        """Itera le frasi di un testo producendo (frase, start, end) assoluti."""
        for match in self._SENTENCE_RE.finditer(text):
            raw = match.group()
            stripped = raw.strip()
            if not stripped:
                continue
            lead = len(raw) - len(raw.lstrip())
            start = base + match.start() + lead
            yield stripped, start, start + len(stripped)

    def _chunk_by_sentences(self, text: str, doc_id: str) -> list[Chunk]:
        """Confeziona frasi complete fino alla dimensione target.

        Tra chunk consecutivi viene ripristinato un overlap di chiusura
        (ultime frasi entro settings.chunk_overlap_tokens) per non perdere
        contesto al confine. Una frase singola più grande del chunk resta
        intera (non viene troncata a metà). I titoli Markdown vengono
        uniti alla frase che li segue: nessun chunk termina con un titolo.
        """
        sentences = list(self._iter_sentences(text))
        if not sentences:
            return self._chunk_raw(text, doc_id)

        # Unisce ogni titolo Markdown alla frase successiva (unità unica)
        units: list[tuple[str, int, int]] = []
        open_heading: Optional[tuple[str, int, int]] = None
        for sentence, s_start, s_end in sentences:
            if self._HEADING_RE.match(sentence):
                open_heading = (sentence, s_start, s_end)
                continue
            if open_heading:
                h_text, h_start, _ = open_heading
                sentence = f"{h_text} {sentence}"
                s_start = h_start
                open_heading = None
            units.append((sentence, s_start, s_end))
        if open_heading:
            units.append(open_heading)  # titolo finale senza contenuto

        chunks: list[Chunk] = []
        pending: list[tuple[str, int, int]] = []
        pending_tokens = 0

        def flush():
            nonlocal pending, pending_tokens
            if not pending:
                return
            chunks.append(Chunk(
                text=" ".join(s for s, _, _ in pending),
                index=0,
                start_char=pending[0][1],
                end_char=pending[-1][2],
                doc_id=doc_id,
            ))
            pending = []
            pending_tokens = 0

        for sentence, s_start, s_end in units:
            s_tokens = max(1, len(sentence) // 4)
            if pending and pending_tokens + s_tokens > self.chunk_size:
                prev_tail = list(pending)
                flush()
                # Overlap: riporta le ultime frasi del chunk precedente
                carried: list[tuple[str, int, int]] = []
                carried_tokens = 0
                for item in reversed(prev_tail):
                    t = max(1, len(item[0]) // 4)
                    if carried and carried_tokens + t > self.overlap_tokens:
                        break
                    carried.insert(0, item)
                    carried_tokens += t
                for item in carried:
                    pending.append(item)
                    pending_tokens += max(1, len(item[0]) // 4)
            pending.append((sentence, s_start, s_end))
            pending_tokens += s_tokens
        flush()

        return chunks

    def _chunk_raw(self, text: str, doc_id: str) -> list[Chunk]:
        """Strategia "fixed": finestra rigida di caratteri con overlap,
        senza rispetto dei confini semantici.

        L'avanzamento è `step = finestra - overlap` (sempre ≥ 1): garantisce
        la terminazione anche con overlap anomali e non genera chunk
        duplicati sulla coda del testo.
        """
        chars_per_chunk = self.chunk_size * 4  # stima approssimativa
        overlap_chars = self.overlap_tokens * 4
        step = max(1, chars_per_chunk - overlap_chars)

        chunks = []
        i = 0
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
            if end >= len(text):
                break
            i += step

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