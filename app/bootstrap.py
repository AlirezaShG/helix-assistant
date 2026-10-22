"""
Data preparation. Runs at startup, and once more at Docker build time so the
container starts with everything ready.

1. Create the SQLite database if it does not exist (app/db/seed.py).
2. Build the vector index if it does not exist or is out of date.

"Out of date" is decided with a fingerprint of everything the index depends
on: the bytes of every PDF, the embedding model, the chunk size and the index
format. Edit or add a PDF, restart, and it is re-indexed automatically;
otherwise startup skips the work.

Run it on its own with:  python -m app.bootstrap
"""

import hashlib
import logging

from app.core.config import Settings, get_settings
from app.db.seed import build_database
from app.rag.chunking import chunk_document
from app.rag.embeddings import Embedder, create_embedder
from app.rag.pdf_preprocessing import parse_pdfs
from app.rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

# Bump when preprocessing, chunking or the index layout changes, to force a rebuild.
INDEX_FORMAT = "2-hybrid"


def documents_fingerprint(settings: Settings, embedder: Embedder) -> str:
    digest = hashlib.sha256()
    digest.update(f"{INDEX_FORMAT}|{embedder.name}|{settings.chunk_max_chars}".encode())
    for pdf in sorted(settings.documents_dir.glob("*.pdf")):
        digest.update(pdf.name.encode())
        digest.update(pdf.read_bytes())
    return digest.hexdigest()


def build_index(settings: Settings, store: VectorStore, fingerprint: str) -> int:
    pdfs = sorted(settings.documents_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found in {settings.documents_dir}")

    chunks = []
    for document in parse_pdfs(pdfs):
        document_chunks = chunk_document(document, settings.chunk_max_chars)
        logger.info("%s: %d blocks -> %d chunks", document.source, len(document.blocks), len(document_chunks))
        chunks.extend(document_chunks)

    store.build(chunks, fingerprint)
    return len(chunks)


def prepare_data(settings: Settings, embedder: Embedder) -> VectorStore:
    if build_database(settings.database_path):
        logger.info("Created the sample database at %s", settings.database_path)

    store = VectorStore(settings.vector_store_dir, embedder)
    fingerprint = documents_fingerprint(settings, embedder)
    if store.stored_fingerprint() == fingerprint:
        logger.info("Vector index is up to date (%d chunks)", store.count())
    else:
        logger.info("Building the vector index from %s ...", settings.documents_dir)
        count = build_index(settings, store, fingerprint)
        logger.info("Indexed %d chunks", count)
    return store


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    current_settings = get_settings()
    prepare_data(current_settings, create_embedder(current_settings))
