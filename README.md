# Helix Assistant: RAG + NL2SQL + Tool-Calling Agents

A small but complete AI assistant for the internal team of a (fictional)
pharmaceutical distributor, **Helix Pharma Distribution**. It answers questions
from two kinds of knowledge:

- **policy documents** (4 PDFs: returns and recalls, cold-chain SOP, credit and
  payment terms, adverse-event reporting) via **RAG**;
- **a sales database** (SQLite: products, customers, orders, order items) via
  **natural language → SQL**.

A **coordinator agent** picks the right sub-agent for each question, can chain
them, and does arithmetic through a **calculator tool**. Every response shows
which sub-agent and tool ran, the generated SQL, and the cited document sections.

```text
"What percentage of delivered revenue in Q1 2026 came from hospitals?"
  → sql_agent   SELECT SUM(oi.quantity * oi.unit_price) AS total_revenue_q1,
                       SUM(CASE WHEN c.customer_type='hospital' THEN ... END) AS hospital_revenue_q1 ...
                → [[12245570500, 8873750500]]
  → calculator  (8873750500 / 12245570500) * 100  =  72.4649823379
  → "The delivered revenue from hospitals in Q1 2026 was 72.46 % of the total delivered revenue."
```

All examples in this README and in [docs/sample_outputs.md](docs/sample_outputs.md)
are real outputs, recorded with **gpt-oss:20b** running locally in Ollama.

---

## Quick start (Docker)

```bash
cp .env.example .env          # then set LLM_BASE_URL / LLM_MODEL / LLM_API_KEY (see below)
docker compose up --build     # first build ~3-5 min (downloads the embedding model)
```

The API listens on <http://localhost:8000> and interactive docs are at
<http://localhost:8000/docs>. The database and vector index are built inside
the image at build time, so the container starts immediately.

```bash
curl -s http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the late payment fee for overdue invoices?"}'
```

Run the tests inside the container:

```bash
docker compose run --rm assistant pytest
```

### Choosing the model

Any **OpenAI-compatible** endpoint whose model supports tool calling works. Set
these in `.env`:

| Variable | Default | Examples |
|---|---|---|
| `LLM_BASE_URL` | `https://api.openai.com/v1` | `https://api.avalai.ir/v1`, `https://openrouter.ai/api/v1`, `http://host.docker.internal:11434/v1` (Ollama on the host) |
| `LLM_MODEL` | `gpt-4o-mini` | `gpt-4o`, `openai/gpt-4o-mini`, `gpt-oss:20b` |
| `LLM_API_KEY` | (required) | your key; for Ollama any non-empty value, e.g. `ollama` |
| `LLM_STRUCTURED_OUTPUT` | `json_schema` | `function_calling` for providers without `response_format` support |
| `EMBEDDING_PROVIDER` | `local` | `openai` (then also set `EMBEDDING_MODEL=text-embedding-3-small`) |

**Local model (no API key, no cost)**, as used for the recorded outputs:

```bash
ollama pull gpt-oss:20b            # ~14 GB; fits a 16 GB GPU
```
```ini
# .env
LLM_BASE_URL=http://host.docker.internal:11434/v1   # without Docker: http://localhost:11434/v1
LLM_MODEL=gpt-oss:20b
LLM_API_KEY=ollama
LLM_TIMEOUT_SECONDS=180
```

On Windows with a system proxy or VPN client, also set
`NO_PROXY=localhost,127.0.0.1` when running without Docker. Otherwise the
OpenAI client sends even local requests through the proxy, which answers 502.

Every other setting (top-k, similarity threshold, SQL timeout, row cap, tool
budget ...) is in [`app/core/config.py`](app/core/config.py) and can be
overridden the same way.

### Running without Docker

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                # configure the model
python -m app.bootstrap                             # database + vector index (downloads the model once)
uvicorn app.main:app --reload
pytest
```

---

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/v1/ask` | Full assistant: coordinator + sub-agents + calculator |
| `POST` | `/api/v1/documents/ask` | Document sub-agent alone (RAG) |
| `POST` | `/api/v1/sql/ask` | SQL sub-agent alone; returns the SQL and the rows |
| `GET` | `/api/v1/health` | Index size, database, LLM configuration |

All three `POST` endpoints take `{"question": "..."}` (1–1000 characters).

**HTTP status convention.** The status code describes the *request*; the
outcome of a valid question is always a normal `200` answer:

| Situation | Response |
|---|---|
| Empty / too long / missing question | `422` with the validation error |
| `LLM_API_KEY` not set | `503` with a message saying so |
| Provider rejects the key / unknown model / unreachable / timeout / rate limit | `502` / `502` / `502` / `504` / `503` |
| Document index not built | `503` |
| Anything unexpected | `500`, details only in the server log |
| Not in the documents | `200`, `found: false`, "The documents do not contain ..." |
| Unsafe SQL, or a request to change data | `200`, `status: "rejected"` or `"no_query"` with the reason |

Example `/ask` response (real, shortened):

```json
{
  "answer": "The delivered revenue from hospitals in Q1 2026 was **72.46 %** of the total delivered revenue.",
  "route": ["sql_agent", "calculator"],
  "steps": [
    {"agent": "sql_agent", "tool": "query_database",
     "input": {"question": "What was the total delivered revenue in Q1 2026, and what was the delivered revenue from hospitals in Q1 2026?"},
     "output": {"status": "ok", "sql": "SELECT SUM(oi.quantity * oi.unit_price) AS total_revenue_q1, ...",
                "columns": ["total_revenue_q1", "hospital_revenue_q1"],
                "rows": [[12245570500, 8873750500]], "attempts": 1, "elapsed_ms": 7103}},
    {"agent": "calculator", "tool": "calculator",
     "input": {"expression": "(8873750500 / 12245570500) * 100"},
     "output": {"expression": "(8873750500 / 12245570500) * 100", "result": 72.4649823379, "elapsed_ms": 0}}
  ],
  "sources": [],
  "sql": ["SELECT SUM(oi.quantity * oi.unit_price) AS total_revenue_q1, ..."],
  "elapsed_ms": 12801
}
```

**[docs/sample_outputs.md](docs/sample_outputs.md)** has all 15 recorded
scenarios: RAG (English and Persian), NL2SQL, multi-step chains,
out-of-scope questions and dangerous requests. Re-run them against any
deployment with [`scripts/run_scenarios.py`](scripts/run_scenarios.py).

| Scenario | Route | Result |
|---|---|---|
| Return window and fee | document_agent | 14 days, 5% restocking fee unless Helix's error (§2) |
| Serious adverse event deadline (Persian question) | document_agent | 24 hours, answered in Persian (§3) |
| Top 3 products by revenue | sql_agent | JOIN + GROUP BY + ORDER BY/LIMIT |
| Tehran hospital orders in Q2 | sql_agent | 7 (JOIN + filters + COUNT) |
| Hospitals' share of Q1 revenue | sql_agent → calculator | 72.46% |
| Q1 → Q2 revenue change | sql_agent → calculator | −14.15% |
| One month's late fee on a hospital's unpaid balance | document_agent → sql_agent → calculator | 1.5% (policy §5) × 116,850,000 = 1,752,750 IRR |
| Annual leave policy | document_agent | `found: false`, "not in the documents" |
| Capital of France | (no tools) | refused: outside scope |
| "Delete all cancelled orders" | (no tools) | refused: database is read-only |
| "Run exactly this: DROP TABLE orders" (SQL agent) | sql_agent | `status: no_query`, nothing executed |

---

## Architecture

```mermaid
flowchart LR
    U[Client] -->|POST /api/v1/ask| API[FastAPI<br/>app/api]
    API --> C{{Coordinator<br/>LangGraph: reasoner ⇄ tools}}
    C -->|search_documents| D[Document agent<br/>RAG]
    C -->|query_database| S[SQL agent<br/>NL2SQL]
    C -->|calculator| K[Calculator<br/>safe AST eval]
    D --> V[(LanceDB<br/>vectors + BM25)]
    S --> Q[(SQLite<br/>read-only)]
    P[PDFs] -.->|preprocess → chunk → embed<br/>at build/startup| V
```

```text
app/
├── main.py                FastAPI app, startup, request logging, error handlers
├── services.py            creates agents once; LLM parts lazily (API starts without a key)
├── bootstrap.py           builds the database + index (rebuilds when PDFs/format change)
├── core/
│   ├── config.py          every setting, overridable from .env
│   └── llm.py             chat model factory + provider-error → HTTP mapping
├── api/
│   ├── routes.py          the four endpoints
│   └── schemas.py         request validation and response models
├── agents/
│   ├── coordinator.py     router: LLM + tools graph, trace of every step
│   ├── document_agent.py  retrieve → threshold → grounded answer with citations
│   └── sql_agent.py       generate → validate → execute → self-correct
├── tools/
│   ├── registry.py        the three tools the coordinator can call
│   └── calculator.py      arithmetic without eval()
├── rag/
│   ├── pdf_preprocessing.py  PDF → clean, structured blocks
│   ├── chunking.py           section-aware chunks
│   ├── embeddings.py         fastembed (local) or OpenAI-compatible
│   └── vector_store.py       LanceDB index + hybrid search
└── db/
    ├── seed.py            deterministic sample data
    ├── schema_context.py  schema + real values for the NL2SQL prompt
    ├── sql_safety.py      safety layer 1: SQL parser checks
    └── executor.py        safety layer 2: read-only SQLite execution
```

Agents, tools, data access and the API are separate packages. Agents never
touch HTTP, and the API never builds prompts.

### 1. Documents → RAG

**Preprocessing** ([`pdf_preprocessing.py`](app/rag/pdf_preprocessing.py)).
Raw `pypdf` text is not fit for embedding, so five steps fix concrete
problems:
1. per-page extraction; pages without a text layer are reported (no OCR here);
2. Unicode NFKC normalisation, plus mapping of broken bullet glyphs (in these
   PDFs the bullet comes out as `U+007F`);
3. removal of the running header (detected as a line repeated on ≥50% of
   pages) and of `Page X of Y` footers;
4. re-joining wrapped lines into paragraphs, and de-hyphenating line breaks;
5. detection of numbered headings and bullets.

**Chunking** ([`chunking.py`](app/rag/chunking.py)). The PDFs are organised
in numbered sections, each roughly one rule, so a chunk is a section (split
between paragraphs if longer than 900 characters). Each chunk is prefixed
with `Document title > Section heading`, so it stands on its own: "Overdue
invoices incur 1.5% ..." becomes findable for "late payment fee". This
produces 30 chunks from the 4 PDFs.

**Embedding.** The default embedding model is
`paraphrase-multilingual-MiniLM-L12-v2` (384-d), running on CPU through
fastembed/ONNX: no PyTorch, no GPU, no API cost. It is baked into the image.
Persian questions are first rewritten into an English search query (one short
LLM call), and the answer comes back in Persian.

**Hybrid retrieval** ([`vector_store.py`](app/rag/vector_store.py)). LanceDB
runs a vector search and a BM25 full-text search (stemmed, stop words
removed), and the two rankings are merged with **reciprocal rank fusion**.
This was added after a real failure: for "a refrigerated product was above
8 °C for 40 minutes", vector search alone ranked the excursion section 6th,
outside the top 5, so the agent rightly said "not found". BM25 ranks it 1st
because "8 °C" and "minutes" appear in it verbatim. With fusion the agent
answers correctly (quarantine, notify QA within 1 hour). A regression test in
`test_retrieval_quality.py` covers this case.

**Grounding: no made-up answers** ([`document_agent.py`](app/agents/document_agent.py)).
Two independent guards:
1. a **similarity threshold** (cosine ≥ 0.30, calibrated, see
   [`config.py`](app/core/config.py)). If no chunk passes it, the agent answers
   "not in the documents" **without calling the LLM at all**;
2. **structured output**. The LLM must return
   `{answerable, answer, cited_ids}`. If it says `answerable=false`, or cites
   no excerpt that was actually retrieved, the answer is discarded and
   "not found" is returned.

### 2. Database → NL2SQL

The schema is [`data/database/schema.sql`](data/database/schema.sql): 4 tables
linked by foreign keys. The data is generated deterministically by
[`app/db/seed.py`](app/db/seed.py) (`random.Random(2026)`): 15 customers,
12 products, 298 orders and 765 order lines (Jan–Sep 2026), identical on every
machine.

**What the model sees** ([`schema_context.py`](app/db/schema_context.py)): the
commented DDL itself (the comments state units, allowed values and the revenue
definition), plus the real values of low-cardinality text columns and the date
range. That way "تهران" becomes `city = 'Tehran'` instead of a guessed spelling.

**Flow** ([`sql_agent.py`](app/agents/sql_agent.py)): the LLM returns
`{sql, reason}` as structured output → layer 1 → layer 2 → rows. If the query
fails to parse or run (e.g. `no such column`), the error is shown to the
model **once** for self-correction. Unsafe SQL is never retried. Nothing is
hard-coded per question.

**Safety: two independent layers**, each tested as if the other did not exist:

| Layer | File | Mechanism |
|---|---|---|
| 1. Static validation | [`sql_safety.py`](app/db/sql_safety.py) | Parsed with **sqlglot** (a real parser, so `SELECT 'drop table'` passes and a `DELETE` hidden in a CTE does not). Exactly one statement, must be a query, no write/DDL/PRAGMA/ATTACH/`SELECT INTO` anywhere in the tree, only the 4 business tables (no `sqlite_master`), no `load_extension` etc. |
| 2. Database level | [`executor.py`](app/db/executor.py) | File opened **read-only** (`mode=ro`). An **authorizer callback** allows only SELECT/READ/FUNCTION. Python's `execute()` refuses multiple statements. A progress handler kills queries after 3 s, and at most 200 rows are fetched. |

### 3. Agents, tools and routing

The [coordinator](app/agents/coordinator.py) is a LangGraph graph of two
nodes: `reasoner` (the LLM with three tools bound) and `tools` (LangGraph's
`ToolNode`), looping until the LLM answers without calling a tool:

| Tool | Component | Used for |
|---|---|---|
| `search_documents(question)` | Document agent | rules, deadlines, procedures |
| `query_database(question)` | SQL agent | figures about sales, customers, products |
| `calculator(expression)` | Calculator | every percentage, difference, ratio, fee |

**Routing** is the LLM's tool choice, steered by precise tool descriptions
([`registry.py`](app/tools/registry.py)) and explicit rules in the system
prompt:
- never answer about Helix from general knowledge;
- send every policy question to the documents, even when the topic seems
  uncovered;
- fetch raw figures with SQL and compute with the calculator;
- report `found=false` honestly;
- refuse data changes.

Multi-step questions are several rounds, e.g. SQL → calculator, or
documents → SQL → calculator. A tool budget (6 rounds) prevents endless loops.
The answer language is detected in code and stated in the prompt, because
the model once answered an English question in Persian.

**The calculator** ([`calculator.py`](app/tools/calculator.py)) parses the
expression into a Python AST and evaluates only whitelisted nodes (numbers,
`+ - * / // % **`, `abs round min max sqrt`). It is not `eval()`, so
`__import__('os')` is rejected, and huge exponents and division by zero give
clear errors.

**Traceability.** Each response has `route` and `steps` (agent, tool, input,
output). The server log shows the same for each request (real excerpt):

```text
13:45:55 INFO app.agents.coordinator | [coordinator] route -> sql_agent (query_database) args={'question': 'What was the total delivered revenue in Q1 2026, and ...'}
13:46:02 INFO app.agents.sql_agent   | [sql_agent] attempt 1 sql="SELECT\n  SUM(oi.quantity * oi.unit_price) AS total_revenue_q1, ..."
13:46:02 INFO app.agents.sql_agent   | [sql_agent] 1 row(s) in 7103 ms
13:46:03 INFO app.agents.coordinator | [coordinator] route -> calculator (calculator) args={'expression': '(8873750500 / 12245570500) * 100'}
13:46:04 INFO app.agents.coordinator | [coordinator] done in 12801 ms, route=['sql_agent', 'calculator']
13:46:04 INFO app                    | POST /api/v1/ask -> 200 (12802 ms)
```

---

## Tests

```bash
pytest                                    # locally
docker compose run --rm assistant pytest  # in the container
```

96 tests. All but the retrieval-quality ones run offline in a few seconds,
with the LLM replaced by a scripted fake ([`tests/fakes.py`](tests/fakes.py)):

| File | Covers |
|---|---|
| `test_sql_safety.py` | 12 attack patterns rejected by layer 1; writes refused by layer 2 even with layer 1 bypassed; row cap; 3 s timeout on an endless recursive CTE |
| `test_sql_agent.py` | SQL executed and checked against the DB; self-correction from the error; injected `DELETE` rejected and not retried; prose instead of structure retried |
| `test_calculator.py` | arithmetic, code-execution attempts, division by zero, huge exponents |
| `test_preprocessing.py` | header/footer removal, line joining, de-hyphenation, section/bullet detection, chunk splitting |
| `test_document_agent.py` | citations, threshold guard (LLM never called), `answerable=false`, invalid citation, Persian path |
| `test_coordinator.py` | the real LangGraph graph: SQL → calculator chain and its trace, document routing, no-tool answers, tool budget |
| `test_api.py` | 422 on bad input, 503 without a key, 502 on a rejected key, 500 without leaking details |
| `test_retrieval_quality.py` | with the **real** embedding model and hybrid search: the answering section reaches the LLM for 9 questions; unrelated questions are filtered out |

The end-to-end behaviour with a real LLM is checked by
`scripts/run_scenarios.py` (15 scenarios). Its numbers were verified against
direct SQL on the database.

---

## Design decisions

- **OpenAI-compatible client instead of a provider SDK**: one setting switches
  between OpenAI, AvalAI, OpenRouter or a local Ollama/vLLM.
- **Local CPU embeddings (fastembed) by default**: no per-query cost, works
  offline, deterministic; the model is in the image. The API backend is one
  setting away.
- **LanceDB and SQLite**: both embedded, so the whole system is one container
  with no external services to start or wait for.
- **Section-aware chunks** rather than fixed-size windows: a policy rule is
  never cut in half, and every chunk carries its section title for citations.
- **Hybrid retrieval with rank fusion**: small embedding models miss exact
  numbers and units, while BM25 misses paraphrases. Fusing ranks avoids
  tuning weights between two incomparable score scales.
- **Structured outputs in `json_schema` mode**: the server constrains
  generation to the schema, so the output always parses. With forced tool
  calls (`function_calling`), gpt-oss occasionally wrote malformed JSON and
  the provider failed the request.
- **Sub-agents return data, the coordinator writes prose**: the SQL agent
  returns SQL + rows, which keeps it testable and lets the coordinator chain it
  with the calculator.
- **Defence in depth for SQL**: the validator gives good error messages; the
  database-level guards make safety independent of the validator being perfect.

## Limitations

- **Small, synthetic corpus.** 4 English PDFs and one SQLite file. For larger
  corpora: an ANN index, metadata filters and a cross-encoder re-ranker.
- **No OCR.** Scanned PDFs are detected and skipped.
- **Routing quality depends on the LLM.** Recorded end to end with
  gpt-oss:20b (local). Cloud models such as gpt-4o-mini use the same protocol
  but were not part of the recorded run.
- **Latency.** 1–15 s per question with a local 20B model on one GPU, since
  multi-step questions make 3–4 LLM calls.
- **Single-turn.** No conversation memory between requests (LangGraph's
  checkpointer would add it).
- **Dates are Gregorian** (`YYYY-MM-DD`); Jalali dates in questions are not
  converted.
- **No auth, rate limiting or async workers**, by design for this scope.

## Credits

The pipeline builds on earlier work of mine: the LangGraph RAG pipeline over
LanceDB and the tool-calling agent graph from
[NLP-Foundations-to-Agents](https://github.com/AlirezaShG/NLP-Foundations-to-Agents)
(notebooks 06 and 07), and the FastAPI service layout and embedding model from
[pharma-risk-intelligence](https://github.com/AlirezaShG/pharma-risk-intelligence).
Helix Pharma Distribution, its documents, customers and figures are fictional.
