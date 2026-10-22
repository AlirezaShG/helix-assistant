"""The evaluation's own scoring functions, and the integrity of the evaluation dataset."""

import sqlite3

import pytest

from evaluation import cases
from evaluation.metrics import contains_number, extract_numbers, has_fact, results_match, retrieval_rank


# ---- reading numbers out of answers -------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("Late fee: **1 752 750 IRR**", [1752750]),  # spaces as thousands separators
    ("1,752,750 IRR", [1752750]),
    ("fell by ‑14.15 %", [-14.15]),  # non-breaking hyphen as minus
    ("between 2-8 °C", [2, 8]),  # a range, not minus eight
    ("حداکثر ۲۴ ساعت", [24]),  # Persian digits
    ("۷۲٫۴۶ درصد", [72.46]),  # Persian decimal separator
    ("about 3.81 billion IRR", [3.81e9]),
    ("Q2 2026", [2, 2026]),
])
def test_extract_numbers(text, expected):
    assert extract_numbers(text) == pytest.approx(expected)


def test_contains_number_tolerates_rounding_but_not_wrong_values():
    assert contains_number("about 72.5 %", 72.4649823)
    assert not contains_number("about 70 %", 72.4649823)
    assert contains_number("decreased by 14.15%", -14.1517, sign_insensitive=True)
    assert not contains_number("decreased by 14.15%", -14.1517)


def test_facts_match_numbers_exactly_and_phrases_as_text():
    assert has_fact("within 5 minutes", 5)
    assert not has_fact("within 15 minutes", 5)  # 5 is not "15"
    assert has_fact("Label it **DO NOT USE**.", "DO NOT USE")


# ---- execution accuracy -----------------------------------------------------------

def test_results_match_allows_extra_columns_and_any_order():
    gold = [["Tehran"]]
    assert results_match(gold, [["Tehran", 5]])
    assert results_match([["a"], ["b"]], [["b", 2], ["a", 1]])


def test_results_match_respects_order_when_it_matters():
    gold = [["Toos"], ["Sahand"], ["Zagros"]]
    assert results_match(gold, [["Toos", 7], ["Sahand", 5], ["Zagros", 4]], ordered=True)
    assert not results_match(gold, [["Sahand", 5], ["Toos", 7], ["Zagros", 4]], ordered=True)


def test_results_match_rejects_wrong_values_and_tolerates_rounding():
    assert not results_match([[100]], [[101]])
    assert results_match([[48509807.692307696]], [[48509807.69]])


def test_results_match_accepts_one_row_instead_of_one_column():
    assert results_match([[10], [20]], [[20, 10]])


def test_retrieval_rank():
    retrieved = [{"chunk_id": "cold_chain_sop-3", "section": "2. Storage"},
                 {"chunk_id": "credit_and_payment_terms-3", "section": "2. Payment terms by customer type"}]
    assert retrieval_rank(retrieved, "credit_and_payment_terms.pdf", "2. Payment terms by customer type") == 2
    assert retrieval_rank(retrieved, "cold_chain_sop.pdf", "5. Transport") is None


# ---- the dataset itself -------------------------------------------------------------

def test_every_expected_section_exists_in_the_pdfs(chunks):
    sections = {(c.source, c.section) for c in chunks}
    for case in cases.DOCUMENT_CASES:
        assert (case.document, case.section) in sections, case.question


def test_every_gold_query_runs_and_returns_data(db_path):
    with sqlite3.connect(db_path) as conn:
        for case in cases.SQL_CASES:
            assert conn.execute(case.gold_sql).fetchall(), case.question
        for case in cases.AGENT_CASES:
            if case.expected_sql:
                value = conn.execute(case.expected_sql).fetchone()[0]
                assert isinstance(value, (int, float)), case.question


def test_ordered_cases_have_an_order_by():
    for case in cases.SQL_CASES:
        assert case.ordered == ("ORDER BY" in case.gold_sql and "LIMIT 1" not in case.gold_sql), case.question
