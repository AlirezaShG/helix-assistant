"""PDF preprocessing and chunking, on the real sample PDFs and on small synthetic cases."""

from app.rag.chunking import chunk_document
from app.rag.pdf_preprocessing import (
    Block, ParsedDocument, _join, find_repeated_lines, is_boilerplate,
)


def test_running_header_and_page_footer_are_removed(chunks):
    for chunk in chunks:
        assert "Internal use only" not in chunk.text
        assert "Page 1 of" not in chunk.text


def test_titles_come_from_pdf_metadata(parsed_documents):
    titles = {doc.source: doc.title for doc in parsed_documents}
    assert titles["credit_and_payment_terms.pdf"] == "Customer Credit and Payment Terms"


def test_sections_and_bullets_are_detected(parsed_documents):
    doc = next(d for d in parsed_documents if d.source == "credit_and_payment_terms.pdf")
    headings = [b.text for b in doc.blocks if b.kind == "heading"]
    assert headings[:3] == ["1. Scope", "2. Payment terms by customer type", "3. Credit limits"]
    bullets = [b.text for b in doc.blocks if b.kind == "bullet"]
    assert "Pharmacies: 30 days." in bullets


def test_wrapped_lines_are_joined_into_one_paragraph(parsed_documents):
    doc = next(d for d in parsed_documents if d.source == "credit_and_payment_terms.pdf")
    late_payment = next(b.text for b in doc.blocks if b.text.startswith("An invoice that is not paid"))
    # In the PDF this sentence spans three visual lines.
    assert "1.5% of the overdue amount for each month, or part of a month, that the invoice remains unpaid." in late_payment


def test_hyphenated_line_breaks_are_rejoined():
    assert _join("pharmaco-", "vigilance training") == "pharmacovigilance training"
    assert _join("2 to 8 °C, see section", "5.") == "2 to 8 °C, see section 5."


def test_repeated_lines_are_detected_across_pages():
    pages = [["ACME confidential", "Intro text"], ["ACME confidential", "More text"], ["ACME confidential", "End"]]
    repeated = find_repeated_lines(pages)
    assert is_boilerplate("ACME confidential", repeated)
    assert not is_boilerplate("Intro text", repeated)
    assert is_boilerplate("Page 3 of 7", repeated) and is_boilerplate("12", repeated)


def test_chunks_follow_sections_and_carry_context(chunks):
    chunk = next(c for c in chunks if c.section == "5. Late payment")
    assert chunk.text.startswith("Customer Credit and Payment Terms > 5. Late payment\n")
    assert chunk.source == "credit_and_payment_terms.pdf" and chunk.page == 1
    assert len({c.chunk_id for c in chunks}) == len(chunks)  # ids are unique


def test_long_sections_are_split_between_blocks_not_inside_them():
    long_paragraphs = [Block("paragraph", f"Sentence {i}. " * 30, 1) for i in range(4)]
    doc = ParsedDocument("x.pdf", "X", [Block("heading", "1. Long section", 1), *long_paragraphs])
    pieces = chunk_document(doc, max_chars=900)
    assert len(pieces) > 1
    assert all(p.text.startswith("X > 1. Long section") for p in pieces)
    assert sum(p.text.count("Sentence") for p in pieces) == 4 * 30  # nothing lost or duplicated
