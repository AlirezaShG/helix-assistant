"""Runs the evaluation set against a running API; writes docs/evaluation.md and .json."""

import argparse
import hashlib
import json
import os
import sqlite3
import statistics
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime

from app.core.config import ROOT_DIR, get_settings
from app.core.llm import create_chat_model
from app.rag.chunking import chunk_document
from app.rag.pdf_preprocessing import parse_pdfs
from evaluation import cases
from evaluation.judge import Judge, Verdict
from evaluation.metrics import contains_number, has_fact, results_match, retrieval_rank

DOCS_DIR = ROOT_DIR / "docs"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(base_url: str, endpoint: str, question: str) -> tuple[int, dict, float]:
    request = urllib.request.Request(
        f"{base_url}/api/v1{endpoint}",
        data=json.dumps({"question": question}).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with HTTP.open(request, timeout=300) as response:
            status, body = response.status, json.load(response)
    except urllib.error.HTTPError as error:
        status, body = error.code, json.loads(error.read() or b"{}")
    return status, body, round(time.perf_counter() - started, 2)


class Evaluation:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.settings = get_settings()
        judge_settings = self.settings.model_copy(
            update={"llm_model": os.environ.get("EVAL_JUDGE_MODEL", self.settings.llm_model)})
        self.judge_model = judge_settings.llm_model
        self.judge = Judge(create_chat_model(judge_settings), self.settings.llm_structured_output)
        self.section_texts = self._section_texts()
        self.latency: dict[str, list[float]] = {}


    def ask(self, endpoint: str, question: str) -> tuple[int, dict]:
        status, body, seconds = call(self.base_url, endpoint, question)
        self.latency.setdefault(endpoint, []).append(seconds)
        print(f"  {endpoint:16} {seconds:5.1f}s  HTTP {status}  {question[:70]}")
        return status, body

    def gold(self, sql: str) -> list[list]:
        """Run a hand-written gold query (trusted code: plain read-only connection)."""
        uri = f"{self.settings.database_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            return [list(row) for row in conn.execute(sql).fetchall()]

    def _section_texts(self) -> dict[tuple[str, str], str]:
        """(document, section) -> text, for the faithfulness judge."""
        texts: dict[tuple[str, str], str] = {}
        for doc in parse_pdfs(sorted(self.settings.documents_dir.glob("*.pdf"))):
            for chunk in chunk_document(doc, self.settings.chunk_max_chars):
                texts[(chunk.source, chunk.section)] = texts.get((chunk.source, chunk.section), "") + chunk.text + "\n"
        return texts

    def database_checksum(self) -> str:
        return hashlib.sha256(self.settings.database_path.read_bytes()).hexdigest()


    def documents(self) -> list[dict]:
        rows = []
        for case in cases.DOCUMENT_CASES:
            status, body = self.ask("/documents/ask", case.question)
            answer, found = body.get("answer", ""), bool(body.get("found"))
            retrieved = body.get("retrieved", [])
            rank = retrieval_rank(retrieved, case.document, case.section)
            reached_llm = rank is not None and retrieved[rank - 1]["score"] >= self.settings.retrieval_min_score

            if found:
                correct = self.judge.correctness(case.question, case.reference, answer)
                cited = "\n".join(self.section_texts.get((s["document"], s["section"]), "")
                                  for s in body.get("sources", []))
                faithful = self.judge.faithfulness(case.question, cited, answer)
            else:
                correct, faithful = Verdict(verdict=False, reason="answered 'not found'"), None

            rows.append({
                "question": case.question, "expected_section": f"{case.document} § {case.section}",
                "http": status, "rank": rank, "reached_llm": reached_llm, "found": found,
                "facts_ok": all(has_fact(answer, f) for f in case.facts) if case.facts else None,
                "correct": correct.verdict, "correct_reason": correct.reason,
                "faithful": faithful.verdict if faithful else None,
                "faithful_reason": faithful.reason if faithful else "",
                "answer": answer,
            })
        return rows

    def unanswerable(self) -> list[dict]:
        rows = []
        for question in cases.UNANSWERABLE_CASES:
            status, body = self.ask("/documents/ask", question)
            rows.append({"question": question, "http": status, "found": bool(body.get("found")),
                         "passed": status == 200 and not body.get("found"), "answer": body.get("answer", "")})
        return rows

    def sql(self) -> list[dict]:
        rows = []
        for case in cases.SQL_CASES:
            status, body = self.ask("/sql/ask", case.question)
            gold_rows = self.gold(case.gold_sql)
            ok = body.get("status") == "ok"
            rows.append({
                "question": case.question, "http": status, "status": body.get("status"),
                "attempts": body.get("attempts"), "sql": body.get("sql"),
                "ran": ok, "passed": ok and results_match(gold_rows, body.get("rows", []), case.ordered),
                "gold_rows": gold_rows[:5], "rows": (body.get("rows") or [])[:5],
            })
        return rows

    def agents(self) -> list[dict]:
        rows = []
        for case in cases.AGENT_CASES:
            status, body = self.ask("/ask", case.question)
            answer, route = body.get("answer", ""), body.get("route", [])
            route_ok = case.must_use <= set(route) and not (case.must_not_use & set(route))

            expected = self.gold(case.expected_sql)[0][0] if case.expected_sql else case.expected
            number_ok = (contains_number(answer, expected, sign_insensitive=case.sign_insensitive)
                         if expected is not None else None)
            facts_ok = all(has_fact(answer, f) for f in case.facts) if case.facts else None
            checks = [check for check in (number_ok, facts_ok) if check is not None]
            answer_ok = all(checks) if checks else None

            rows.append({
                "question": case.question, "http": status, "route": route,
                "expected_route": sorted(case.must_use) or ["(no tools)"],
                "route_ok": route_ok, "expected": expected, "answer_ok": answer_ok,
                "passed": status == 200 and route_ok and answer_ok is not False,
                "answer": answer,
            })
        return rows

    def safety(self) -> list[dict]:
        rows = []
        for case in cases.SAFETY_CASES:
            status, body = self.ask(case.endpoint, case.question)
            if case.endpoint == "/sql/ask":
                refused = body.get("status") in ("no_query", "rejected")
                reason = f"status {body.get('status')}: {body.get('error') or body.get('explanation')}"
                answer = reason
            else:
                answer = body.get("answer", "")
                verdict = self.judge.refusal(case.question, answer)
                refused, reason = verdict.verdict, verdict.reason
            rows.append({"endpoint": case.endpoint, "question": case.question, "http": status,
                         "passed": status == 200 and refused, "reason": reason, "answer": answer})
        return rows

    def run(self) -> dict:
        """One full pass over the evaluation set."""
        self.latency = {}
        checksum_before = self.database_checksum()
        groups = {}
        for name in ("documents", "unanswerable", "sql", "agents", "safety"):  # safety last
            print(f"[{name}]")
            groups[name] = getattr(self, name)()
        return {
            "date": datetime.now().isoformat(timespec="seconds"),
            "health": json.load(HTTP.open(f"{self.base_url}/api/v1/health", timeout=10)),
            "judge_model": self.judge_model,
            "reasoning_effort": self.settings.llm_reasoning_effort or "provider default",
            "top_k": self.settings.retrieval_top_k,
            "threshold": self.settings.retrieval_min_score,
            "database_unchanged": self.database_checksum() == checksum_before,
            "latency": self.latency,
            **groups,
        }


METRICS = [
    ("Retrieval: answer section reaches the LLM (hybrid top-k, above threshold)", "documents", "reached_llm"),
    ("RAG: answer correct (LLM judge vs reference)", "documents", "correct"),
    ("RAG: answer faithful to its cited sections (LLM judge, answered cases)", "documents", "faithful"),
    ("RAG: required facts present (exact match)", "documents", "facts_ok"),
    ('RAG: says "not found" for questions the documents do not cover', "unanswerable", "passed"),
    ("NL2SQL: execution accuracy (rows equal the gold query's)", "sql", "passed"),
    ("NL2SQL: query ran successfully", "sql", "ran"),
    ("Agents: correct route (required components used, wrong ones not)", "agents", "route_ok"),
    ("Agents: correct final number / facts", "agents", "answer_ok"),
    ("Agents: fully correct (route and answer)", "agents", "passed"),
    ("Safety: write / bypass requests refused", "safety", "passed"),
]


def rate(cases: list[dict], field: str) -> tuple[int, int]:
    values = [case[field] for case in cases if case[field] is not None]
    return sum(1 for value in values if value), len(values)


def describe(per_run: list[tuple[int, int]]) -> str:
    passed, total = sum(p for p, _ in per_run), sum(t for _, t in per_run)
    if not total:
        return "n/a"
    overall = f"{passed}/{total} ({100 * passed / total:.0f}%)"
    if len(per_run) == 1:
        return overall
    return overall + "; per run: " + ", ".join(f"{100 * p / t:.0f}%" for p, t in per_run)


def tally(values: list) -> str:
    """One case across runs: ✅/❌ for a single run, "✅ 3/3" or "⚠️ 2/3" for several."""
    counted = [v for v in values if v is not None]
    if not counted:
        return "–"
    if len(values) == 1:
        return "✅" if counted[0] else "❌"
    passed = sum(1 for v in counted if v)
    icon = "✅" if passed == len(counted) else ("⚠️" if passed else "❌")
    return f"{icon} {passed}/{len(counted)}"


def percentile_95(values: list[float]) -> float:
    return sorted(values)[max(0, round(0.95 * len(values)) - 1)]


def number(value) -> str:
    if value is None:
        return "–"
    return f"{value:,.0f}" if abs(value) >= 10_000 else f"{value:,.4g}"


def summary_rows(runs: list[dict]) -> list[tuple[str, str]]:
    rows = [(label, describe([rate(run[group], field) for run in runs])) for label, group, field in METRICS]
    mrr = statistics.mean(1 / d["rank"] if d["rank"] else 0 for run in runs for d in run["documents"])
    retries = sum(1 for run in runs for s in run["sql"] if (s["attempts"] or 0) > 1)
    rows.insert(1, ("Retrieval: mean reciprocal rank of the answer section", f"{mrr:.2f}"))
    rows.append(("NL2SQL: answers that needed the self-correction retry",
                 f"{retries}/{sum(len(run['sql']) for run in runs)}"))
    rows.append(("Safety: database file unchanged after every run",
                 "yes" if all(run["database_unchanged"] for run in runs) else "NO"))
    for endpoint in runs[0]["latency"]:
        times = [t for run in runs for t in run["latency"].get(endpoint, [])]
        rows.append((f"Latency {endpoint}: median / p95",
                     f"{statistics.median(times):.1f} s / {percentile_95(times):.1f} s"))
    return rows


def column(runs: list[dict], group: str, index: int, field: str) -> list:
    return [run[group][index][field] for run in runs]


def first_failure_note(runs: list[dict], index: int) -> str:
    for run in runs:
        d = run["documents"][index]
        if not d["correct"]:
            return d["correct_reason"]
        if d["faithful"] is False:
            return d["faithful_reason"]
    return ""


def to_markdown(runs: list[dict]) -> str:
    first, h = runs[0], runs[0]["health"]
    out = [
        "# Evaluation", "",
        f"Run on {first['date']} by `python -m evaluation.run --repeat {len(runs)}`; questions and gold answers "
        "are in [evaluation/cases.py](../evaluation/cases.py). "
        f"System LLM: `{h['llm_model']}` (reasoning effort: {first['reasoning_effort']}); judge LLM: "
        f"`{first['judge_model']}`; embeddings: `{h['embedding_model']}`; top-k {first['top_k']}, "
        f"similarity threshold {first['threshold']}.", "",
        f"{len(first['documents'])} document questions, {len(first['unanswerable'])} unanswerable questions, "
        f"{len(first['sql'])} SQL questions, {len(first['agents'])} agent questions and {len(first['safety'])} "
        f"safety requests, in English and Persian, each asked {len(runs)} time(s).", "",
        "## Summary", "", "| Metric | Result |", "|---|---|",
        *[f"| {name} | {value} |" for name, value in summary_rows(runs)], "",
        "## Documents (RAG)", "",
        "| Question | Expected section | Rank | Correct | Faithful | Facts | Judge's note on a failure |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, d in enumerate(first["documents"]):
        out.append(f"| {d['question']} | {d['expected_section']} | {d['rank'] or '–'} "
                   f"| {tally(column(runs, 'documents', i, 'correct'))} "
                   f"| {tally(column(runs, 'documents', i, 'faithful'))} "
                   f"| {tally(column(runs, 'documents', i, 'facts_ok'))} | {first_failure_note(runs, i)} |")
    out += ["", "## Unanswerable questions", "", "| Question | Said not found |", "|---|---|"]
    out += [f"| {u['question']} | {tally(column(runs, 'unanswerable', i, 'passed'))} |"
            for i, u in enumerate(first["unanswerable"])]
    out += ["", "## NL2SQL", "", "| Question | Matches gold | Max attempts |", "|---|---|---|"]
    out += [f"| {s['question']} | {tally(column(runs, 'sql', i, 'passed'))} "
            f"| {max(a or 0 for a in column(runs, 'sql', i, 'attempts'))} |" for i, s in enumerate(first["sql"])]
    out += ["", "## Agents (end to end)", "",
            "| Question | Route (run 1) | Expected route | Route ok | Expected | Answer ok |",
            "|---|---|---|---|---|---|"]
    for i, a in enumerate(first["agents"]):
        out.append(f"| {a['question']} | {' → '.join(a['route']) or '(no tools)'} | {', '.join(a['expected_route'])} "
                   f"| {tally(column(runs, 'agents', i, 'route_ok'))} | {number(a['expected'])} "
                   f"| {tally(column(runs, 'agents', i, 'answer_ok'))} |")
    out += ["", "## Safety", "", "| Endpoint | Request | Refused | Detail (run 1) |", "|---|---|---|---|"]
    out += [f"| `{s['endpoint']}` | {s['question']} | {tally(column(runs, 'safety', i, 'passed'))} | {s['reason']} |"
            for i, s in enumerate(first["safety"])]
    out += ["", "## How to read this", "",
            "- **Gold answers are independent of the system**: SQL gold values come from hand-written queries run "
            "directly on the database; document references are taken from the PDFs.",
            "- **Execution accuracy** compares result rows, not SQL text; extra columns are allowed.",
            "- **Numbers in answers** match within 1% (\"72.5 %\" matches 72.46...); Persian digits and "
            "thousands separators are normalised.",
            "- **Repeated runs**: the local model is not fully deterministic, so each question was asked several "
            "times; \"⚠️ 2/3\" means it passed in 2 of 3 runs.",
            "- **LLM judge caveat**: correctness, faithfulness and refusal are judged by an LLM. When the judge "
            "is the same model as the system it may be lenient; every negative verdict is listed with its reason.",
            "- Every request and response is in [evaluation.json](evaluation.json).", ""]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--repeat", type=int, default=1,
                        help="run the whole set N times (the model is not fully deterministic)")
    args = parser.parse_args()

    evaluation = Evaluation(args.base_url)
    runs = []
    for run_number in range(1, args.repeat + 1):
        print(f"=== run {run_number}/{args.repeat}")
        runs.append(evaluation.run())

    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "evaluation.json").write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2, default=str),
                                              encoding="utf-8", newline="\n")
    (DOCS_DIR / "evaluation.md").write_text(to_markdown(runs), encoding="utf-8", newline="\n")
    print("\n".join(f"{name}: {value}" for name, value in summary_rows(runs)))
    print("wrote docs/evaluation.md and docs/evaluation.json")


if __name__ == "__main__":
    main()
