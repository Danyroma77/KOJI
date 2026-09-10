"""
=============================================================================
DOCUMENT PARSER — FACTORY PATTERN
=============================================================================

Implementa un parser factory che seleziona il parser corretto in base
all'estensione del file. Ogni parser implementa l'interfaccia parse() → ParseResult.

FORMATI SUPPORTATI:
- PDF: PyMuPDF con fallback OCR per scansioni
- DOCX: python-docx
- ODT: estrazione XML content.xml
- HTML: BeautifulSoup
- Markdown: markdown library
- Email: email.parser (EML)
- Testo: decodifica UTF-8

METADATI ESTRATTI:
- Title: titolo del documento
- Author: autore
- Pages: numero pagine (PDF)
- Language: lingua (default italiano)

FACTORY PATTERN:
- BaseParser: interfaccia astratta
- Parser specifici: implementazioni per ogni formato
- get_parser(): factory che restituisce il parser corretto
"""

from __future__ import annotations
import hashlib
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from datetime import datetime

import fitz  # PyMuPDF
from docx import Document
from bs4 import BeautifulSoup
import markdown
from email import policy
from email.parser import BytesParser

from app.config import settings


class ParseResult:
    """
    Risultato del parsing: testo grezzo + metadati strutturali.
    
    Contiene il testo estratto e i metadati che possono essere inferiti
    dal contenuto o dai metadati del file.
    """

    def __init__(self, text: str, title: Optional[str] = None,
                 author: Optional[str] = None, pages: Optional[int] = None,
                 language: str = "it"):
        self.text = text
        self.title = title
        self.author = author
        self.pages = pages
        self.language = language


class BaseParser(ABC):
    """
    Interfaccia base per tutti i parser.
    
    Ogni parser deve implementare il metodo parse() che estrae testo
    e metadati dal file.
    """

    @abstractmethod
    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        """
        Estrae testo e metadati dal file.
        
        Args:
            file_bytes: Contenuto binario del file.
            filename: Nome originale del file (per inferire metadati).
            
        Returns:
            ParseResult con testo e metadati.
        """
        ...


class PDFParser(BaseParser):
    """Parser per documenti PDF (testuali e scansionati con fallback OCR)."""

    # Separatore di pagina usato per preservare i confini di pagina
    # nel testo estratto. Il chunk manager può usarlo per la strategia "page".
    PAGE_BREAK = "\f"

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages_text = []

        for page in doc:
            text = page.get_text("text")
            if text.strip():
                pages_text.append(text)
            else:
                # Tentativo OCR per PDF scansionati
                text = self._ocr_fallback(page)
                pages_text.append(text)

        # Unisce le pagine con un separatore speciale per preservare
        # i confini di pagina (usato dalla strategia di chunking "page")
        full_text = self.PAGE_BREAK.join(pages_text)

        # Metadati dai metadati PDF
        meta = doc.metadata
        title = meta.get("title") or Path(filename).stem
        author = meta.get("author")

        doc.close()
        return ParseResult(
            text=full_text,
            title=title,
            author=author,
            pages=len(pages_text),
        )

    def _ocr_fallback(self, page) -> str:
        """Fallback OCR con Tesseract per PDF scansionati."""
        try:
            import subprocess
            # Renderizza pagina come immagine PPM
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("ppm")

            # Chiamata a tesseract
            result = subprocess.run(
                ["tesseract", "stdin", "stdout", "-l", "ita+eng"],
                input=img_bytes,
                capture_output=True,
                timeout=30,
            )
            return result.stdout.decode("utf-8", errors="replace")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return ""


class DOCXParser(BaseParser):
    """Parser per documenti Word (.docx)."""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        # python-docx richiede un file-like object, non bytes grezzi
        # ('bytes' object has no attribute 'seek')
        from io import BytesIO
        doc = Document(BytesIO(file_bytes))

        paragraphs = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                # Preserva indicatori di livello titolo
                style_name = para.style.name if para.style else ""
                if "Heading" in style_name or "Titolo" in style_name:
                    level = "".join(c for c in style_name if c.isdigit()) or "1"
                    paragraphs.append(f"{'#' * int(level)} {text}")
                else:
                    paragraphs.append(text)

        # Tabelle
        for table in doc.tables:
            table_rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                table_rows.append("| " + " | ".join(cells) + " |")
            if table_rows:
                # Header pipe
                header_cols = len(table_rows[0].split("|")) - 2
                if header_cols > 0:
                    table_rows.insert(1, "| " + " --- |" * header_cols)
                paragraphs.append("\n".join(table_rows))

        # Metadati core properties
        title = doc.core_properties.title or Path(filename).stem
        author = doc.core_properties.author

        return ParseResult(
            text="\n\n".join(paragraphs),
            title=title,
            author=author,
        )


class HTMLParser(BaseParser):
    """Parser per documenti HTML."""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        soup = BeautifulSoup(file_bytes, "html.parser")

        # Rimuovi script e style
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # Titolo dalla pagina
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else Path(filename).stem

        # Estrai testo con struttura
        content = []
        for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th"]):
            tag = element.name
            text = element.get_text(strip=True)
            if not text:
                continue
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(tag[1])
                content.append(f"{'#' * level} {text}")
            elif tag == "li":
                content.append(f"- {text}")
            else:
                content.append(text)

        return ParseResult(text="\n\n".join(content), title=title)


class MarkdownParser(BaseParser):
    """Parser per file Markdown — restituisce il testo così com'è."""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        text = file_bytes.decode("utf-8", errors="replace")
        # Inferisci titolo dalla prima linea che inizia con #
        title = Path(filename).stem
        for line in text.split("\n"):
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break
        return ParseResult(text=text, title=title)


class EmailParser(BaseParser):
    """Parser per file email (.eml)."""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        msg = BytesParser(policy=policy.default).parsebytes(file_bytes)

        parts = []
        # Corpo testuale
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        parts.append(payload.decode("utf-8", errors="replace"))
                elif ct == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        soup = BeautifulSoup(payload, "html.parser")
                        parts.append(soup.get_text(separator="\n", strip=True))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                parts.append(payload.decode("utf-8", errors="replace"))

        # Metadati
        subject = str(msg.get("Subject", "")) or Path(filename).stem
        # Decodifica subject se encoded
        try:
            from email.header import decode_header
            decoded = decode_header(subject)
            subject = " ".join(
                part.decode(enc or "utf-8") if isinstance(part, bytes) else part
                for part, enc in decoded
            )
        except Exception:
            pass

        author = str(msg.get("From", ""))

        # Costruisci rappresentazione
        header = f"# {subject}\n\n**Da:** {author}\n**Data:** {msg.get('Date', 'N/D')}\n\n---\n\n"
        body = "\n\n".join(parts)

        return ParseResult(text=header + body, title=subject, author=author)


class MsgParser(BaseParser):
    """Parser per file email di Outlook (.msg).

    Il formato MSG di Outlook è binario (OLEF/COM, CFBF). Si usa ``extract-msg``
    come primo tentativo; in ambiente Windows con Outlook installato, viene
    tentato il fallback su COM (MAPI). Il parser restituisce corpo + header
    comuni (oggetto, mittente, data).
    """

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        import os
        from tempfile import NamedTemporaryFile

        tmp_path = None
        try:
            with NamedTemporaryFile(delete=False, suffix=".msg") as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name

            # 1) extract-msg
            try:
                from extract_msg import Message

                msg = Message(tmp_path)
                subject = msg.subject or Path(filename).stem
                author = msg.sender or None
                body = msg.body or ""
                if not body:
                    body = getattr(msg, "htmlBody", "") or ""
                    if body:
                        from bs4 import BeautifulSoup

                        body = BeautifulSoup(body, "html.parser").get_text("\n", strip=True)

                date = None
                try:
                    date = msg.get("Sent") or msg.get("Date") or None
                except Exception:
                    date = None

                header = (
                    f"# {subject}\n\n**Da:** {author or 'N/D'}"
                    f"\n**Data:** {date or 'N/D'}\n\n---\n\n"
                )
                return ParseResult(text=header + body, title=subject, author=author)
            except Exception:
                pass

            # 2) win32com (Outlook COM) su Windows
            try:
                import win32com.client

                outlook = win32com.client.Dispatch("Outlook.Application")
                namespace = outlook.GetNamespace("MAPI")
                mail = namespace.OpenSharedItem(tmp_path)
                subject = getattr(mail, "Subject", None) or Path(filename).stem
                author = getattr(mail, "Sender", None) or None
                if not isinstance(author, str):
                    try:
                        author = getattr(author, "Name", None) or author
                    except Exception:
                        author = None
                body = getattr(mail, "Body", "") or ""
                html = getattr(mail, "HTMLBody", "")
                if not body and html:
                    from bs4 import BeautifulSoup

                    body = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
                date = None
                try:
                    sent = getattr(mail, "SentOn", None)
                    if sent:
                        date = str(sent)
                except Exception:
                    pass

                header = (
                    f"# {subject}\n\n**Da:** {author or 'N/D'}"
                    f"\n**Data:** {date or 'N/D'}\n\n---\n\n"
                )
                return ParseResult(text=header + body, title=subject, author=author)
            except Exception:
                pass

            # Fallback: nessuna estrazione automatica
            return ParseResult(text="", title=Path(filename).stem)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


class TextParser(BaseParser):
    """Parser per file di testo semplice (.txt)."""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        text = file_bytes.decode("utf-8", errors="replace")
        title = Path(filename).stem
        return ParseResult(text=text, title=title)


class ODTParser(BaseParser):
    """Parser per documenti ODT — estrazione XML content.xml."""

    def parse(self, file_bytes: bytes, filename: str) -> ParseResult:
        from io import BytesIO
        import zipfile
        import xml.etree.ElementTree as ET
        import re

        def extract_text_from_odt(data: bytes) -> str:
            """Estrae testo da un ODT valido."""
            with zipfile.ZipFile(BytesIO(data)) as zf:
                content_xml = zf.read("content.xml")

            root = ET.fromstring(content_xml)
            # Namespace ODF
            ns = {"text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0"}

            paragraphs = []
            for p in root.iter("{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"):
                # Estrai tutto il testo del paragrafo usando itertext()
                # che include sia text che tail degli elementi
                text = "".join(p.itertext()).strip()
                if text:
                    paragraphs.append(text)

            return "\n\n".join(paragraphs)

        try:
            text = extract_text_from_odt(file_bytes)
            return ParseResult(
                text=text,
                title=Path(filename).stem,
            )
        except Exception:
            # Fallback: tenta di estrarre testo grezzo dall'XML
            try:
                with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
                    # Cerca content.xml o qualsiasi file XML
                    xml_files = [n for n in zf.namelist() if n.endswith(".xml")]
                    if xml_files:
                        content_xml = zf.read(xml_files[0]).decode("utf-8", errors="replace")
                        # Rimuovi tag XML, mantieni testo
                        text = re.sub(r"<[^>]+>", " ", content_xml)
                        text = re.sub(r"\s+", " ", text).strip()
                        return ParseResult(text=text, title=Path(filename).stem)
            except Exception:
                pass
            # Fallback finale: restituisci testo vuoto
            return ParseResult(text="", title=Path(filename).stem)


# === Factory ===

PARSER_MAP = {
    ".pdf": PDFParser,
    ".docx": DOCXParser,
    ".odt": ODTParser,
    ".html": HTMLParser,
    ".htm": HTMLParser,
    ".md": MarkdownParser,
    ".markdown": MarkdownParser,
    ".eml": EmailParser,
    ".msg": MsgParser,
    ".txt": TextParser,
}


def get_parser(filename: str) -> BaseParser:
    """Restituisce il parser appropriato per il file.

    Args:
        filename: Nome del file con estensione.

    Returns:
        Istanza del parser corretto.

    Raises:
        ValueError: Se il formato non è supportato.
    """
    ext = Path(filename).suffix.lower()
    parser_class = PARSER_MAP.get(ext)
    if parser_class is None:
        supported = ", ".join(sorted(PARSER_MAP.keys()))
        raise ValueError(f"Formato non supportato: {ext}. Formati supportati: {supported}")
    return parser_class()


def parse_document(file_bytes: bytes, filename: str) -> ParseResult:
    """Funzione principale: parsifica un documento.

    Args:
        file_bytes: Contenuto binario del file.
        filename: Nome originale del file.

    Returns:
        ParseResult con testo e metadati.
    """
    parser = get_parser(filename)
    return parser.parse(file_bytes, filename)


def compute_sha256(file_bytes: bytes) -> str:
    """Calcola hash SHA-256 del file."""
    return hashlib.sha256(file_bytes).hexdigest()