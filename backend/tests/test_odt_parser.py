"""
Test per ODTParser — verifica l'estrazione di testo da documenti ODT.
"""
import pytest
from app.services.document_parser import ODTParser, get_parser, parse_document


class TestODTParser:
    """Test per il parser di documenti ODT."""

    def setup_method(self):
        """Inizializza il parser per ogni test."""
        self.parser = ODTParser()

    def test_parse_simple_odt(self, simple_odt):
        """Verifica il parsing di un ODT semplice con paragrafi."""
        result = self.parser.parse(simple_odt, "test.odt")
        
        assert result.text is not None
        assert len(result.text) > 0
        assert "Primo paragrafo del documento." in result.text
        assert "Secondo paragrafo con testo più lungo." in result.text
        assert "Terzo paragrafo finale." in result.text

    def test_parse_title_from_filename(self, simple_odt):
        """Verifica che il titolo sia estratto dal nome del file."""
        result = self.parser.parse(simple_odt, "mio_documento.odt")
        assert result.title == "mio_documento"

    def test_parse_paragraphs_separated_by_newlines(self, simple_odt):
        """Verifica che i paragrafi siano separati da doppio newline."""
        result = self.parser.parse(simple_odt, "test.odt")
        paragraphs = result.text.split("\n\n")
        assert len(paragraphs) == 3

    def test_parse_with_spans(self, odt_with_spans):
        """Verifica il parsing di ODT con span stilizzati."""
        result = self.parser.parse(odt_with_spans, "test.odt")
        
        assert "Testo in grassetto" in result.text
        assert "testo normale" in result.text
        assert "Span separato" in result.text

    def test_parse_empty_odt(self, odt_empty):
        """Verifica il parsing di un ODT vuoto."""
        result = self.parser.parse(odt_empty, "vuoto.odt")
        
        assert result.text == ""
        assert result.title == "vuoto"

    def test_parse_whitespace_only(self, odt_whitespace_only):
        """Verifica che paragrafi con solo spazzi vengano ignorati."""
        result = self.parser.parse(odt_whitespace_only, "spazzi.odt")
        
        assert result.text == ""

    def test_parse_unicode(self, odt_unicode):
        """Verifica il parsing di caratteri Unicode."""
        result = self.parser.parse(odt_unicode, "unicode.odt")
        
        assert "accénti" in result.text
        assert "€" in result.text
        assert "🎉" in result.text

    def test_parse_invalid_file_fallback(self, invalid_odt):
        """Verifica che file invalidi attivino il fallback."""
        result = self.parser.parse(invalid_odt, "invalido.odt")
        
        # Il fallback deve restituire un ParseResult valido
        assert result is not None
        assert result.title == "invalido"

    def test_parse_no_content_xml_fallback(self, odt_no_content_xml):
        """Verifica che ODT senza content.xml attivino il fallback."""
        result = self.parser.parse(odt_no_content_xml, "senza_content.odt")
        
        assert result is not None
        assert result.title == "senza_content"


class TestODTParserViaFactory:
    """Test per il parser ODT attraverso la factory."""

    def test_get_parser_returns_odt_parser(self):
        """Verifica che get_parser restituisca ODTParser per .odt."""
        parser = get_parser("documento.odt")
        assert isinstance(parser, ODTParser)

    def test_parse_document_odt(self, simple_odt):
        """Verifica il parsing completo tramite parse_document."""
        result = parse_document(simple_odt, "test.odt")
        
        assert result.text is not None
        assert "Primo paragrafo" in result.text

    def test_parse_document_case_insensitive(self, simple_odt):
        """Verifica che l'estensione sia case-insensitive."""
        result = parse_document(simple_odt, "TEST.ODT")
        assert result.text is not None
        assert "Primo paragrafo" in result.text


class TestODTParserEdgeCases:
    """Test per casi edge dell'ODT parser."""

    def test_parse_large_odt(self):
        """Verifica il parsing di un ODT con molti paragrafi."""
        # Crea un ODT con 100 paragrafi
        paragraphs = "\n".join(
            f"<text:p>Paragrafo numero {i} con contenuto di test.</text:p>"
            for i in range(100)
        )
        content = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
    <office:body>
        <office:text>
            {paragraphs}
        </office:text>
    </office:body>
</office:document-content>"""
        
        from tests.conftest import create_odt_bytes
        odt_bytes = create_odt_bytes(content)
        
        parser = ODTParser()
        result = parser.parse(odt_bytes, "grande.odt")
        
        assert "Paragrafo numero 0" in result.text
        assert "Paragrafo numero 99" in result.text
        assert len(result.text.split("\n\n")) == 100

    def test_parse_special_characters_in_text(self):
        """Verifica il parsing di caratteri speciali XML."""
        content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
    <office:body>
        <office:text>
            <text:p>Testo con &lt;tag&gt; &amp; &quot;quotes&quot;</text:p>
        </office:text>
    </office:body>
</office:document-content>"""
        
        from tests.conftest import create_odt_bytes
        odt_bytes = create_odt_bytes(content)
        
        parser = ODTParser()
        result = parser.parse(odt_bytes, "special.odt")
        
        # Le entità XML devono essere decodificate
        assert "<tag>" in result.text or "&lt;tag&gt;" in result.text
        assert "&" in result.text or "&amp;" in result.text

    def test_parse_preserves_order(self, simple_odt):
        """Verifica che l'ordine dei paragrafi sia preservato."""
        result = ODTParser().parse(simple_odt, "test.odt")
        
        pos1 = result.text.index("Primo")
        pos2 = result.text.index("Secondo")
        pos3 = result.text.index("Terzo")
        
        assert pos1 < pos2 < pos3