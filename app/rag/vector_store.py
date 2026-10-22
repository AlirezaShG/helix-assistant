"""
LanceDB store: build the index from chunks, then search it (hybrid retrieval).

LanceDB is embedded (a folder on disk, no server process), which keeps the
whole system in one container. It is the same store the Persian legal RAG and
the travel-agent notebooks use. With a few dozen chunks LanceDB does an exact
(brute-force) vector search, so there is no approximate-index tuning.

Why hybrid: vector search alone ranked the right section 6th for "a
refrigerated product was above 8 °C for 40 minutes" (the small embedding model
matched other cold-chain sections more closely), while keyword search (BM25)
ranked it 1st because "8 °C" and "minutes" appear in it verbatim. Each method
covers the other's blind spot, so both run and their rankings are merged.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import lancedb
import numpy as np
from lancedb.index import FTS

from app.rag.chunking import Chunk
from app.rag.embeddings import Embedder

logger = logging.getLogger(__name__)

TABLE_NAME = "chunks"
MANIFEST_FILE = "manifest.json"
RRF_K = 60  # the usual constant for reciprocal rank fusion (Cormack et al., 2009)


class IndexNotReadyError(RuntimeError):
    """The vector index has not been built (or could not be built)."""


@dataclass
class SearchHit:
    chunk_id: str
    source: str
    title: str
    section: str
    page: int
    text: str
    score: float  # cosine similarity to the query: 1.0 = same meaning, around 0 = unrelated


class VectorStore:
    def __init__(self, directory: Path, embedder: Embedder):
        self.directory = directory
        self.embedder = embedder

    # ---- building -----------------------------------------------------------

    def build(self, chunks: list[Chunk], fingerprint: str) -> None:
        vectors = self.embedder.embed_documents([chunk.text for chunk in chunks])
        rows = [{**asdict(chunk), "vector": vector} for chunk, vector in zip(chunks, vectors)]
        self.directory.mkdir(parents=True, exist_ok=True)
        table = lancedb.connect(self.directory).create_table(TABLE_NAME, data=rows, mode="overwrite")
        # Full-text (BM25) index for the keyword half of hybrid search:
        # lower-cased, stemmed ("returns" ~ "return"), English stop words removed.
        table.create_index("text", config=FTS(), replace=True)
        # The fingerprint records what the index was built from (documents,
        # embedding model, chunk size); bootstrap rebuilds when it changes.
        (self.directory / MANIFEST_FILE).write_text(
            json.dumps({"fingerprint": fingerprint, "chunks": len(rows)}), encoding="utf-8")

    def stored_fingerprint(self) -> str | None:
        manifest = self.directory / MANIFEST_FILE
        if not manifest.exists():
            return None
        return json.loads(manifest.read_text(encoding="utf-8")).get("fingerprint")

    def count(self) -> int:
        try:
            return self._table().count_rows()
        except IndexNotReadyError:
            return 0

    # ---- searching ----------------------------------------------------------

    def search(self, query: str, top_k: int) -> list[SearchHit]:
        """Hybrid search: vector similarity + BM25 keywords, merged by reciprocal rank fusion.

        Every hit still reports its *cosine similarity* as `score`, so the
        document agent's relevance threshold means the same thing as before.
        """
        table = self._table()
        query_vector = np.asarray(self.embedder.embed_query(query))
        pool = max(top_k * 4, 20)  # candidates taken from each ranking before merging

        semantic = table.search(query_vector.tolist()).distance_type("cosine").limit(pool).to_list()
        try:
            keyword = table.search(query, query_type="fts").limit(pool).to_list()
        except Exception as exc:  # e.g. a query the full-text parser rejects: fall back to vectors only
            logger.warning("keyword search failed (%s); using vector search only", exc)
            keyword = []

        # Reciprocal rank fusion: each ranking gives a chunk 1 / (60 + rank).
        # Ranks are used rather than raw scores because cosine similarity and
        # BM25 live on different scales. A chunk near the top of either list
        # rises; one near the top of both rises most.
        fused: dict[str, float] = {}
        rows_by_id: dict[str, dict] = {}
        for ranking in (semantic, keyword):
            for rank, row in enumerate(ranking, start=1):
                fused[row["chunk_id"]] = fused.get(row["chunk_id"], 0.0) + 1.0 / (RRF_K + rank)
                rows_by_id[row["chunk_id"]] = row
        best = sorted(fused, key=fused.get, reverse=True)[:top_k]

        hits = []
        for chunk_id in best:
            row = rows_by_id[chunk_id]
            hits.append(SearchHit(
                chunk_id=chunk_id, source=row["source"], title=row["title"],
                section=row["section"], page=row["page"], text=row["text"],
                score=round(_cosine(query_vector, row["vector"]), 4),
            ))
        return hits

    def _table(self):
        try:
            return lancedb.connect(self.directory).open_table(TABLE_NAME)
        except Exception as exc:  # LanceDB raises different errors for "missing" across versions
            raise IndexNotReadyError("The document index is not built yet.") from exc


def _cosine(a: np.ndarray, b) -> float:
    b = np.asarray(b, dtype=float)
    return float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))
