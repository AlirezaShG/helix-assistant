"""LanceDB store: build the index from chunks, then search it (hybrid retrieval)."""

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
RRF_K = 60


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
    score: float


class VectorStore:
    def __init__(self, directory: Path, embedder: Embedder):
        self.directory = directory
        self.embedder = embedder


    def build(self, chunks: list[Chunk], fingerprint: str) -> None:
        vectors = self.embedder.embed_documents([chunk.text for chunk in chunks])
        rows = [{**asdict(chunk), "vector": vector} for chunk, vector in zip(chunks, vectors)]
        self.directory.mkdir(parents=True, exist_ok=True)
        table = lancedb.connect(self.directory).create_table(TABLE_NAME, data=rows, mode="overwrite")
        table.create_index("text", config=FTS(), replace=True)
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


    def search(self, query: str, top_k: int) -> list[SearchHit]:
        """Hybrid search: vector similarity + BM25 keywords, merged by reciprocal rank fusion."""
        table = self._table()
        query_vector = np.asarray(self.embedder.embed_query(query))
        pool = max(top_k * 4, 20)

        semantic = table.search(query_vector.tolist()).distance_type("cosine").limit(pool).to_list()
        try:
            keyword = table.search(query, query_type="fts").limit(pool).to_list()
        except Exception as exc:
            logger.warning("keyword search failed (%s); using vector search only", exc)
            keyword = []

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
        except Exception as exc:
            raise IndexNotReadyError("The document index is not built yet.") from exc


def _cosine(a: np.ndarray, b) -> float:
    b = np.asarray(b, dtype=float)
    return float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) or 1.0))
