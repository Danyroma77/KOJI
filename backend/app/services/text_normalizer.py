"""
Text Normalizer — Trasforma testo grezzo in Markdown uniforme.
Rimuove noise, deduplica blocchi, gestisce tabelle.
"""

from __future__ import annotations
import re
import hashlib
from typing import Optional


class TextNormalizer:
    """Normalizza testo da qualsiasi sorgente in Markdown pulito."""

    def __init__(
        self,
        remove_headers: bool = True,
        remove_page_numbers: bool = True,
        remove_watermarks: bool = True,
        dedup_blocks: bool = True,
        min_block_length: int = 20,
    ):
        self.remove_headers = remove_headers
        self.remove_page_numbers = remove_page_numbers
        self.remove_watermarks = remove_watermarks
        self.dedup_blocks = dedup_blocks
        self.min_block_length = min_block_length

    # Separatore di pagina usato dal PDFParser (deve corrispondere)
    PAGE_BREAK = "\f"
    # Placeholder temporaneo per preservare i separatori di pagina
    # durante la normalizzazione. Deve essere una stringa che:
    # 1. Non viene rimossa da strip() o _final_cleanup
    # 2. Non viene trattata come titolo da _clean_headings (non tutto maiuscolo)
    # Ogni placeholder è univoco per evitare che venga rimosso da _deduplicate_blocks
    _PAGE_PLACEHOLDER_PREFIX = "koji_page_break_placeholder_"

    def normalize(self, text: str) -> str:
        """Pipeline completa di normalizzazione.

        Args:
            text: Testo grezzo estratto dal parser.

        Returns:
            Testo normalizzato in Markdown.
        """
        if not text or not text.strip():
            return ""

        # 0. Preserva i separatori di pagina prima della normalizzazione
        # (il carattere \f verrebbe altrimenti alterato da _normalize_whitespace
        # e _deduplicate_blocks rimuoverebbe i duplicati)
        has_page_breaks = self.PAGE_BREAK in text
        if has_page_breaks:
            # Usa placeholder unici per evitare che vengano rimossi da deduplicazione
            page_count = 0
            result = []
            for char in text:
                if char == self.PAGE_BREAK:
                    result.append(f"{self._PAGE_PLACEHOLDER_PREFIX}{page_count}")
                    page_count += 1
                else:
                    result.append(char)
            text = "".join(result)

        # 1. Normalizzazione spaziatura
        text = self._normalize_whitespace(text)

        # 2. Rimozione header/footer ripetuti
        if self.remove_headers:
            text = self._remove_repeated_headers(text)

        # 3. Rimozione numeri di pagina
        if self.remove_page_numbers:
            text = self._remove_page_numbers(text)

        # 4. Rimozione watermark
        if self.remove_watermarks:
            text = self._remove_watermarks(text)

        # 5. Pulizia titoli
        text = self._clean_headings(text)

        # 6. Deduplicazione blocchi
        if self.dedup_blocks:
            text = self._deduplicate_blocks(text)

        # 7. Pulizia finale
        text = self._final_cleanup(text)

        # 8. Ripristina i separatori di pagina alla fine
        if has_page_breaks:
            # Ripristina tutti i placeholder unici
            for i in range(page_count):
                placeholder = f"{self._PAGE_PLACEHOLDER_PREFIX}{i}"
                text = text.replace(placeholder, self.PAGE_BREAK)

        return text.strip()

    def _normalize_whitespace(self, text: str) -> str:
        """Normalizza spaziatura: a capo singoli, niente spazi multipli."""
        # Converti \r\n e \r in \n
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Rimuovi spazi multipli nelle righe
        text = re.sub(r"[^\S\n]+", " ", text)
        # Più di 3 a capo → 2 (paragrafo)
        text = re.sub(r"\n{4,}", "\n\n", text)
        return text

    def _remove_repeated_headers(self, text: str) -> str:
        """Rimuove blocchi che si ripetono identici più di 2 volte
        (tipici header/footer di documenti PDF)."""
        lines = text.split("\n")
        if len(lines) < 10:
            return text

        # Trova linee che appaiono più del 40% delle volte
        line_counts = {}
        for line in lines:
            stripped = line.strip()
            if len(stripped) < 5:
                continue
            h = hashlib.md5(stripped.encode()).hexdigest()
            line_counts[h] = line_counts.get(h, 0) + 1

        threshold = len(lines) * 0.4
        to_remove = {h for h, c in line_counts.items() if c >= threshold}

        filtered = []
        for line in lines:
            h = hashlib.md5(line.strip().encode()).hexdigest()
            if h not in to_remove:
                filtered.append(line)

        return "\n".join(filtered)

    def _remove_page_numbers(self, text: str) -> str:
        """Rimuove numeri di pagina isolati su una riga."""
        lines = text.split("\n")
        filtered = []
        for line in lines:
            stripped = line.strip()
            # Numero isolato (es. "12", "— 12 —", "Pagina 12")
            if re.match(r"^[\s\-—]*\d{1,4}[\s\-—]*$", stripped):
                continue
            if re.match(r"^pagin[ae]\s+\d{1,4}$", stripped, re.IGNORECASE):
                continue
            filtered.append(line)
        return "\n".join(filtered)

    def _remove_watermarks(self, text: str) -> str:
        """Rimuove watermark comuni (BOZZA, CONFIDENZIALE, ecc.)."""
        watermarks = [
            r"\bBOZZA\b",
            r"\bDRAFT\b",
            r"\bCONFIDENZIALE\b",
            r"\bCOP[AI]A\s+INTERNA\b",
        ]
        for pattern in watermarks:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        return text

    def _clean_headings(self, text: str) -> str:
        """Pulisce e normalizza i titoli in formato Markdown."""
        lines = text.split("\n")
        result = []

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Già in formato Markdown heading
            if re.match(r"^#{1,6}\s", stripped):
                # Normalizza spazi dopo #
                stripped = re.sub(r"^(#{1,6})\s+", r"\1 ", stripped)
                result.append(stripped)
                i += 1
                continue

            # Riga TUTTO MAIUSCOLO potenzialmente un titolo
            if (stripped.isupper() and len(stripped) > 3
                    and not stripped.startswith(("-", "*", "|"))
                    and not re.match(r"^[\d\.\)]+", stripped)):
                # Controlla se la riga successiva è vuota o una sottolineatura
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if next_line == "" or re.match(r"^[=\-]{3,}$", next_line):
                    # Diventa un ## titolo
                    result.append(f"## {stripped.title()}")
                    if re.match(r"^[=\-]{3,}$", next_line):
                        i += 1  # Salta la linea di sottolineatura
                    i += 1
                    continue

            # Numerazione stile "1. Titolo" o "1.1 Titolo"
            num_match = re.match(r"^(\d+(?:\.\d+)*)\s+(.+)$", stripped)
            if num_match and len(stripped) < 100:
                num, title = num_match.groups()
                level = num.count(".") + 1
                level = min(level, 4)
                result.append(f"{'#' * level} {title}")
                i += 1
                continue

            result.append(line)
            i += 1

        return "\n".join(result)

    def _deduplicate_blocks(self, text: str) -> str:
        """Rimuove blocchi di testo duplicati consecutivi."""
        blocks = re.split(r"\n{2,}", text)
        seen = set()
        unique = []

        for block in blocks:
            stripped = block.strip()
            if not stripped or len(stripped) < self.min_block_length:
                unique.append(block)
                continue
            h = hashlib.md5(stripped.encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(block)

        return "\n\n".join(unique)

    def _final_cleanup(self, text: str) -> str:
        """Pulizia finale: righe vuote multiple, spazi a inizio/fine riga."""
        # Rimuovi spazi a inizio/fine riga
        lines = [line.strip() for line in text.split("\n")]
        # Rimuovi paragrafi vuoti multipli
        result = []
        prev_empty = False
        for line in lines:
            if line == "":
                if not prev_empty:
                    result.append(line)
                prev_empty = True
            else:
                prev_empty = False
                result.append(line)

        return "\n".join(result)


# Istanza singleton
normalizer = TextNormalizer()