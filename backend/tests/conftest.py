"""
Fixture per i test dei benchmark E1-E7.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_questions():
    """Domande di test per i benchmark."""
    return [
        {
            "question": "Qual è la procedura per ottenere il rimborso?",
            "relevant_docs": ["doc001", "doc002"],
        },
        {
            "question": "Come si richiede il cambio piano?",
            "relevant_docs": ["doc003"],
        },
    ]


@pytest.fixture
def mock_config():
    """Configurazione base per i benchmark."""
    from app.models import BenchmarkConfig, BenchmarkExperiment

    return BenchmarkConfig(
        experiment=BenchmarkExperiment.E4,
        label="Test Run",
        models=["phi3:3.8b"],
        top_k=5,
    )


@pytest.fixture
def mock_vector_store():
    """Mock del vector store per i test."""
    mock = MagicMock()
    mock.count = 100
    mock.initialize = MagicMock()

    # Mock search che restituisce risultati fittizi
    async def mock_search(query, mode="hybrid", top_k=5):
        results = [
            {"id": "doc001_0", "score": 0.9, "text": "Risultato test 1"},
            {"id": "doc002_0", "score": 0.8, "text": "Risultato test 2"},
            {"id": "doc003_0", "score": 0.7, "text": "Risultato test 3"},
        ][:top_k]
        return results, 50.0  # risultati + latency_ms

    mock.search = mock_search
    return mock


@pytest.fixture
def mock_llm_manager():
    """Mock del LLM manager per i test."""
    mock = MagicMock()
    mock.active_model = "phi3:3.8b"

    async def mock_generate(prompt, model=None, **kwargs):
        return {
            "response": "Questa è una risposta di test dal LLM.",
            "tokens_per_second": 25.5,
            "error": None,
        }

    mock.generate = mock_generate
    return mock


@pytest.fixture
def mock_rag_engine():
    """Mock del RAG engine per i test."""
    mock = MagicMock()

    async def mock_query(question, **kwargs):
        return {
            "answer": "Risposta RAG con fonti.",
            "sources": [
                {"id": "doc001_0", "title": "Documento 1", "score": 0.9},
                {"id": "doc002_0", "title": "Documento 2", "score": 0.8},
            ],
        }

    mock.query = mock_query
    return mock


@pytest.fixture
def mock_wiki_generator():
    """Mock del wiki generator per i test."""
    mock = MagicMock()

    async def mock_search(query, top_k=3):
        return [
            {"id": "page1", "title": "Pagina Wiki 1", "score": 0.85},
            {"id": "page2", "title": "Pagina Wiki 2", "score": 0.75},
        ]

    mock.search = mock_search
    return mock


@pytest.fixture
def mock_graph_builder():
    """Mock del graph builder per i test."""
    mock = MagicMock()
    mock.search_entities = AsyncMock(
        return_value=[
            {"id": "entity1", "label": "Entità 1", "score": 0.9},
            {"id": "entity2", "label": "Entità 2", "score": 0.8},
        ]
    )
    return mock


@pytest.fixture
def mock_metrics_store():
    """Mock del metrics store per i test."""
    mock = MagicMock()
    mock.processing_summary.return_value = {
        "phases": {
            "parsing": 1.5,
            "normalization": 0.8,
            "chunking": 2.1,
            "embedding": 5.3,
        }
    }
    return mock


@pytest.fixture
def mock_document_service():
    """Mock del document service per i test."""
    mock = MagicMock()
    mock.get_documents.return_value = [
        {
            "id": "doc001",
            "title": "Documento Test 1",
            "normalized": True,
            "chunks": 5,
        },
        {
            "id": "doc002",
            "title": "Documento Test 2",
            "normalized": True,
            "chunks": 3,
        },
    ]
    return mock


@pytest.fixture
def benchmark_env(mock_vector_store, mock_llm_manager, mock_rag_engine,
                  mock_wiki_generator, mock_graph_builder, mock_metrics_store):
    """Ambiente completo per i test dei benchmark con tutti i mock."""
    return {
        "vector_store": mock_vector_store,
        "llm_manager": mock_llm_manager,
        "rag_engine": mock_rag_engine,
        "wiki_generator": mock_wiki_generator,
        "graph_builder": mock_graph_builder,
        "metrics_store": mock_metrics_store,
    }


import pytest


def create_odt_bytes(content_xml: str, meta_xml: str = None) -> bytes:
    """
    Crea un file ODT valido in memoria per i test.
    
    Args:
        content_xml: Contenuto XML del file content.xml
        meta_xml: Contenuto XML del file meta.xml (opzionale)
        
    Returns:
        Bytes del file ODT (ZIP) valido
    """
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype deve essere il primo file e non compresso per compatibilità
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        zf.writestr("content.xml", content_xml)
        zf.writestr("meta.xml", meta_xml or """<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0">
    <office:meta/>
</office:document-meta>""")
        zf.writestr("styles.xml", """<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0">
    <office:styles/>
</office:document-styles>""")
        # META-INF/manifest.xml richiesto per ODT valido
        zf.writestr("META-INF/manifest.xml", """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">
    <manifest:file-entry manifest:media-type="application/vnd.oasis.opendocument.text" manifest:full-path="/"/>
    <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/>
    <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="meta.xml"/>
    <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="styles.xml"/>
</manifest:manifest>""")
    return buffer.getvalue()


@pytest.fixture
def simple_odt():
    """ODT semplice con paragrafi di testo."""
    content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
    <office:body>
        <office:text>
            <text:p>Primo paragrafo del documento.</text:p>
            <text:p>Secondo paragrafo con testo più lungo.</text:p>
            <text:p>Terzo paragrafo finale.</text:p>
        </office:text>
    </office:body>
</office:document-content>"""
    return create_odt_bytes(content)


@pytest.fixture
def odt_with_spans():
    """ODT con span stilizzati all'interno dei paragrafi."""
    content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
    <office:body>
        <office:text>
            <text:p><text:span>Testo in grassetto</text:span> e testo normale.</text:p>
            <text:p><text:span>Span separato</text:span></text:p>
        </office:text>
    </office:body>
</office:document-content>"""
    return create_odt_bytes(content)


@pytest.fixture
def odt_empty():
    """ODT vuoto senza paragrafi."""
    content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
    <office:body>
        <office:text>
        </office:text>
    </office:body>
</office:document-content>"""
    return create_odt_bytes(content)


@pytest.fixture
def odt_whitespace_only():
    """ODT con paragrafi contenenti solo spazi bianchi."""
    content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
    <office:body>
        <office:text>
            <text:p>   </text:p>
            <text:p>
</text:p>
        </office:text>
    </office:body>
</office:document-content>"""
    return create_odt_bytes(content)


@pytest.fixture
def odt_unicode():
    """ODT con caratteri Unicode (accenti, simboli)."""
    content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
    <office:body>
        <office:text>
            <text:p>Testo con accénti e caratteri speciali: à è é ì ò ù</text:p>
            <text:p>Simboli: € £ ¥ © ® ™</text:p>
            <text:p>Emoji: 🎉 🚀 💡</text:p>
        </office:text>
    </office:body>
</office:document-content>"""
    return create_odt_bytes(content)


@pytest.fixture
def odt_nested_paragraphs():
    """ODT con paragrafi annidati (sezioni)."""
    content = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
                         xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">
    <office:body>
        <office:text>
            <text:p>Introduzione</text:p>
            <text:p>Contenuto principale</text:p>
            <text:p>Conclusione</text:p>
        </office:text>
    </office:body>
</office:document-content>"""
    return create_odt_bytes(content)


@pytest.fixture
def invalid_odt():
    """File non valido (non è un ZIP)."""
    return b"questo non e' un file odt valido"


@pytest.fixture
def odt_no_content_xml():
    """ODT senza file content.xml."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        zf.writestr("meta.xml", "<?xml version='1.0'?><meta/>")
    return buffer.getvalue()