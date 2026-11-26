import pytest
from fastapi.testclient import TestClient

from medusa.core.config import Settings
from medusa.main import create_app


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    # isolate tests from the developer's .env and shell environment
    for key in list(__import__("os").environ):
        if key.startswith("MEDUSA_"):
            monkeypatch.delenv(key)
    return Settings(_env_file=None, environment="test", db_path=tmp_path / "test.db",
                    upload_dir=tmp_path / "uploads", log_level="DEBUG")


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:  # context manager runs the lifespan (logging + database init)
        yield c


@pytest.fixture(scope="session")
def demo_documents():
    """The synthetic demo bundle as Phase 2 ingestion stores it: canonical text + parsed header, as domain Documents."""
    import hashlib
    from medusa.core.config import PROJECT_ROOT
    from medusa.ingestion.metadata import parse_header
    from medusa.ingestion.service import make_document_id
    from medusa.ingestion.text_extraction import normalize_text
    from medusa.schemas.domain import Document

    docs = []
    for path in sorted((PROJECT_ROOT / "data" / "demo" / "SYN-0001").glob("*.txt")):
        raw = path.read_bytes()
        text = normalize_text(raw.decode("utf-8-sig"))
        header = parse_header(text, "SYN-0001")
        docs.append(Document(document_id=make_document_id("SYN-0001", raw), patient_id="SYN-0001",
                             document_type=header.document_type, document_date=header.document_date,
                             metadata=header.fields, text=text, filename=path.name, sha256=hashlib.sha256(raw).hexdigest()))
    return docs


@pytest.fixture(scope="session")
def demo_claims(demo_documents):
    from medusa.analysis.rule_extractor import build_context, extract_claims
    from medusa.analysis.segmentation import segment
    ctx = build_context(demo_documents)
    return [c for d in demo_documents for c in extract_claims(d, segment(d.document_id, d.text), ctx).claims]
