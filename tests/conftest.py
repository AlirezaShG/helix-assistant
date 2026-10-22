from pathlib import Path

import pytest

from app.core.config import ROOT_DIR
from app.db.seed import build_database
from app.rag.chunking import chunk_document
from app.rag.pdf_preprocessing import parse_pdfs
from app.rag.vector_store import VectorStore
from tests.fakes import HashEmbedder

DOCUMENTS_DIR = ROOT_DIR / "data" / "documents"


@pytest.fixture(scope="session")
def pdf_paths() -> list[Path]:
    return sorted(DOCUMENTS_DIR.glob("*.pdf"))


@pytest.fixture(scope="session")
def parsed_documents(pdf_paths):
    return parse_pdfs(pdf_paths)


@pytest.fixture(scope="session")
def chunks(parsed_documents):
    return [chunk for doc in parsed_documents for chunk in chunk_document(doc)]


@pytest.fixture(scope="session")
def db_path(tmp_path_factory) -> Path:
    """A fresh copy of the sample database for the test session."""
    path = tmp_path_factory.mktemp("db") / "helix.db"
    build_database(path)
    return path


@pytest.fixture(scope="session")
def hash_store(tmp_path_factory, chunks) -> VectorStore:
    """The real PDFs indexed with the offline HashEmbedder."""
    store = VectorStore(tmp_path_factory.mktemp("vs"), HashEmbedder())
    store.build(chunks, fingerprint="test")
    return store
