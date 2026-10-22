"""
Scoring functions: deterministic, no LLM involved (tested in tests/test_evaluation_metrics.py).

    extract_numbers / contains_number   find a number in a free-text answer, however it is written
    has_fact                            does the answer contain a required number or phrase?
    results_match                       execution accuracy: do two SQL results hold the same data?
    retrieval_rank                      where did the expected section land in the retrieved list?
"""

import math
import re
import unicodedata

# Persian and Arabic-Indic digits, plus the Arabic decimal/thousands separators.
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬", "01234567890123456789.,")
DASHES = str.maketrans({"‑": "-", "‐": "-", "‒": "-", "–": "-", "−": "-"})

SCALE_WORDS = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "bn": 1e9,
               "هزار": 1e3, "میلیون": 1e6, "میلیارد": 1e9}

# A number: optional minus (only when it is not a range dash like "2-8"), then either digits
# grouped by thousands separators ("1,752,750", "8 256 990 000") or plain digits, then an optional
# decimal part and an optional scale word ("3.8 billion").
NUMBER_RE = re.compile(
    r"(?:(?<![\w.])-)?"
    r"(?<![\d.,])(?:\d{1,3}(?:[ ,]\d{3})+(?![\d])|\d+)(?:\.\d+)?"
    r"(?:\s*(" + "|".join(SCALE_WORDS) + r")\b)?"
)


def normalize(text: str) -> str:
    """Lower-case, ASCII digits, plain dashes, single spaces (NFKC also turns no-break spaces into spaces)."""
    text = unicodedata.normalize("NFKC", str(text)).translate(DIGITS).translate(DASHES)
    return " ".join(text.lower().split())


def extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in NUMBER_RE.finditer(normalize(text)):
        raw = match.group(0)
        scale = SCALE_WORDS.get(match.group(1) or "", 1.0)
        digits = raw[: match.start(1) - match.start(0)] if match.group(1) else raw
        numbers.append(float(digits.replace(",", "").replace(" ", "")) * scale)
    return numbers


def contains_number(text: str, expected: float, rel_tol: float = 0.01, sign_insensitive: bool = False) -> bool:
    """True if the text mentions `expected` within 1% (so "72.46 %" and "72.5 %" both match 72.4649...)."""
    target = abs(expected) if sign_insensitive else expected
    for value in extract_numbers(text):
        value = abs(value) if sign_insensitive else value
        if math.isclose(value, target, rel_tol=rel_tol, abs_tol=1e-9):
            return True
    return False


def has_fact(answer: str, fact) -> bool:
    """A number must appear as a number (so 5 does not match "15"); a phrase as a substring."""
    if isinstance(fact, (int, float)):
        return any(math.isclose(value, fact, abs_tol=1e-9) for value in extract_numbers(answer))
    return normalize(fact) in normalize(answer)


# ---- SQL execution accuracy -------------------------------------------------

def _same_value(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-4, abs_tol=1e-6)  # tolerates ROUND(x, 2)
    return str(a).strip().casefold() == str(b).strip().casefold()


def _same_column(gold: list, predicted: list, ordered: bool) -> bool:
    if not ordered:
        gold, predicted = sorted(gold, key=repr), sorted(predicted, key=repr)
    return all(_same_value(g, p) for g, p in zip(gold, predicted))


def results_match(gold_rows: list, predicted_rows: list, ordered: bool = False) -> bool:
    """Execution accuracy, as in the Spider benchmark, with two allowances:

    - extra columns in the prediction are fine (a "top 3 customers" answer may add the revenue);
    - a one-column gold result may come back as one row (cold-chain vs other revenue as two
      columns instead of two rows).
    """
    gold_rows = [list(r) for r in gold_rows]
    predicted_rows = [list(r) for r in predicted_rows]

    if gold_rows and len(gold_rows[0]) == 1 and len(predicted_rows) == 1 and len(gold_rows) > 1:
        values = list(predicted_rows[0])
        for (gold_value,) in gold_rows:  # every gold value must appear among the row's values
            match = next((i for i, v in enumerate(values) if _same_value(gold_value, v)), None)
            if match is None:
                return False
            values.pop(match)
        return True

    if len(gold_rows) != len(predicted_rows):
        return False
    if not gold_rows:
        return True

    # Map each gold column to a distinct predicted column holding the same values ...
    gold_columns = [list(c) for c in zip(*gold_rows)]
    predicted_columns = [list(c) for c in zip(*predicted_rows)]
    mapping = []
    for gold_column in gold_columns:
        match = next((i for i, column in enumerate(predicted_columns)
                      if i not in mapping and _same_column(gold_column, column, ordered)), None)
        if match is None:
            return False
        mapping.append(match)

    # ... then check that the values also line up row by row.
    projected = [[row[i] for i in mapping] for row in predicted_rows]
    if not ordered:
        gold_rows, projected = sorted(gold_rows, key=repr), sorted(projected, key=repr)
    return all(all(_same_value(g, p) for g, p in zip(gr, pr)) for gr, pr in zip(gold_rows, projected))


# ---- retrieval ----------------------------------------------------------------

def retrieval_rank(retrieved: list[dict], document: str, section: str) -> int | None:
    """1-based rank of the expected section in the retrieved list, or None if absent."""
    stem = document.rsplit(".", 1)[0]
    for rank, hit in enumerate(retrieved, start=1):
        if hit["section"] == section and hit["chunk_id"].startswith(stem + "-"):
            return rank
    return None
