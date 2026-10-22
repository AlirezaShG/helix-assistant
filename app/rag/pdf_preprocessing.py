"""
PDF -> clean, structured text blocks.

Raw pypdf output is not good enough to embed directly. Each step below fixes a
concrete problem with it:

1. Extraction per page (pypdf). Pages without a text layer (scanned images)
   are reported and skipped; OCR is out of scope here. The Persian legal RAG
   project used DeepSeek-OCR for that case, and it could be plugged in here.
2. Unicode NFKC normalisation: ligatures such as "ﬁ" become "fi", and unusual
   spaces become normal ones, so the same word always looks the same. Bullet
   glyphs come out of PDFs as odd code points (here U+007F, in Word exports
   often U+F0B7), so they are mapped back to "•".
3. Boilerplate removal: the running header that repeats on most pages and the
   "Page X of Y" footer are dropped. Left in, they would be part of every
   chunk and make all chunks look similar to each other.
4. Line re-joining: PDF text comes back as visual lines. Wrapped lines are
   joined back into paragraphs, and words hyphenated at a line break are
   re-joined.
5. Structure detection: numbered headings ("3. Cold-chain products") and
   bullets are recognised, so the chunker can split along sections and every
   chunk knows which section it came from (used in the citations).
"""

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger(__name__)

# "3. Cold-chain products", "4.2. Transport": a number with a dot, then a capital letter.
HEADING_RE = re.compile(r"^\d+(\.\d+)*\.\s+[A-Z]")
BULLET_RE = re.compile(r"^[•*-]\s+")
# Code points that bullet glyphs turn into after extraction -> "•".
BULLET_GLYPHS = str.maketrans({c: "•" for c in "\x7f\x95●▪◦"})
PAGE_FOOTER_RE = re.compile(r"\bpage\s+\d+\s+(of|/)\s+\d+\b", re.IGNORECASE)
PAGE_NUMBER_ONLY_RE = re.compile(r"^(page\s*)?\d+(\s*(/|of)\s*\d+)?$", re.IGNORECASE)


@dataclass
class Block:
    kind: str  # "heading" | "paragraph" | "bullet"
    text: str
    page: int


@dataclass
class ParsedDocument:
    source: str  # file name, shown in citations
    title: str
    blocks: list[Block] = field(default_factory=list)


def parse_pdfs(pdf_paths: list[Path]) -> list[ParsedDocument]:
    """Parse several PDFs. Boilerplate is detected across all of them together,
    which also works when each document has only one or two pages."""
    raw = {path: extract_lines_per_page(path) for path in pdf_paths}
    all_pages = [page for pages in raw.values() for page in pages]
    repeated = find_repeated_lines(all_pages)
    return [to_document(path, pages, repeated) for path, pages in raw.items()]


def extract_lines_per_page(pdf_path: Path) -> list[list[str]]:
    """Steps 1 + 2: text of every page as a list of normalised, non-empty lines."""
    pages = []
    for number, page in enumerate(PdfReader(pdf_path).pages, start=1):
        text = unicodedata.normalize("NFKC", page.extract_text() or "").translate(BULLET_GLYPHS)
        if not text.strip():
            logger.warning("%s page %d has no text layer (scanned?) and is skipped", pdf_path.name, number)
        lines = [" ".join(line.split()) for line in text.splitlines()]
        pages.append([line for line in lines if line])
    return pages


def _shape(line: str) -> str:
    # "Page 1 of 2" and "Page 2 of 2" should count as the same line.
    return re.sub(r"\d+", "#", line.lower())


def find_repeated_lines(pages: list[list[str]], min_share: float = 0.5) -> set[str]:
    """Step 3a: lines (by shape) that occur on at least `min_share` of all pages."""
    counts = Counter()
    for lines in pages:
        counts.update({_shape(line) for line in lines})  # count once per page
    threshold = max(2, min_share * len(pages))
    return {shape for shape, count in counts.items() if count >= threshold}


def is_boilerplate(line: str, repeated: set[str]) -> bool:
    """Step 3b."""
    return (
        _shape(line) in repeated
        or PAGE_FOOTER_RE.search(line) is not None
        or PAGE_NUMBER_ONLY_RE.match(line) is not None
    )


def _continues_previous(previous: str, line: str) -> bool:
    """Step 4: is `line` the wrapped continuation of `previous`?

    A new paragraph starts when the previous line closed a sentence and the new
    one starts with a capital letter. Splitting a long paragraph in two by
    mistake is harmless, because the chunker keeps a section together anyway.
    """
    return not previous.endswith((".", ":", "?", "!")) or line[:1].islower()


def _join(previous: str, line: str) -> str:
    # "pharmaco-" + "vigilance" -> "pharmacovigilance"
    if previous.endswith("-") and previous[-2:-1].isalpha() and line[:1].islower():
        return previous[:-1] + line
    return previous + " " + line


def _document_title(reader: PdfReader, pdf_path: Path) -> str:
    meta_title = (reader.metadata.title if reader.metadata else None) or ""
    return meta_title.strip() or pdf_path.stem.replace("_", " ").title()


def to_document(pdf_path: Path, pages: list[list[str]], repeated: set[str]) -> ParsedDocument:
    """Steps 3-5 for one document."""
    title = _document_title(PdfReader(pdf_path), pdf_path)
    blocks: list[Block] = []
    title_lines_to_skip = title

    for page_number, lines in enumerate(pages, start=1):
        for line in lines:
            if is_boilerplate(line, repeated):
                continue

            # The title is printed at the top of page 1 (possibly wrapped over
            # two lines). We already have it from the metadata, so skip it.
            if title_lines_to_skip and title_lines_to_skip.startswith(line):
                title_lines_to_skip = title_lines_to_skip[len(line):].lstrip()
                continue
            title_lines_to_skip = ""

            previous = blocks[-1] if blocks else None
            starts_fresh = previous is None or previous.kind == "heading" or previous.text.endswith(".")

            if HEADING_RE.match(line) and len(line) < 80 and not line.endswith(".") and starts_fresh:
                blocks.append(Block("heading", line, page_number))
            elif BULLET_RE.match(line):
                blocks.append(Block("bullet", BULLET_RE.sub("", line), page_number))
            elif previous and previous.kind != "heading" and _continues_previous(previous.text, line):
                previous.text = _join(previous.text, line)
            else:
                blocks.append(Block("paragraph", line, page_number))

    return ParsedDocument(source=pdf_path.name, title=title, blocks=blocks)
