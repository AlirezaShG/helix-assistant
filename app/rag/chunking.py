"""Section-aware chunking."""

from dataclasses import dataclass

from app.rag.pdf_preprocessing import Block, ParsedDocument


@dataclass
class Chunk:
    chunk_id: str  # "<file stem>-<n>", stable between runs
    source: str  # PDF file name
    title: str  # document title
    section: str  # section heading
    page: int  # page where the chunk starts
    text: str


def chunk_document(doc: ParsedDocument, max_chars: int = 900) -> list[Chunk]:
    sections = _group_by_section(doc)
    chunks: list[Chunk] = []
    stem = doc.source.rsplit(".", 1)[0]

    for heading, blocks in sections:
        header = f"{doc.title} > {heading}"
        current: list[Block] = []

        def flush() -> None:
            if not current:
                return
            body = "\n".join(("- " if b.kind == "bullet" else "") + b.text for b in current)
            chunks.append(Chunk(
                chunk_id=f"{stem}-{len(chunks) + 1}",
                source=doc.source,
                title=doc.title,
                section=heading,
                page=current[0].page,
                text=f"{header}\n{body}",
            ))
            current.clear()

        for block in blocks:
            current_size = len(header) + sum(len(b.text) + 3 for b in current)
            if current and current_size + len(block.text) > max_chars:
                flush()
            current.append(block)
        flush()

    return chunks


def _group_by_section(doc: ParsedDocument) -> list[tuple[str, list[Block]]]:
    """[(heading, blocks under it)]."""
    sections: list[tuple[str, list[Block]]] = []
    for block in doc.blocks:
        if block.kind == "heading":
            sections.append((block.text, []))
        else:
            if not sections:
                sections.append(("Introduction", []))
            sections[-1][1].append(block)
    return [(heading, blocks) for heading, blocks in sections if blocks]
