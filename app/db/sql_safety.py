"""
Layer 1 of SQL safety: static validation of LLM-generated SQL before it runs.

The SQL is written by a language model that reads user text, so it is
untrusted input. The query is parsed with sqlglot, a real SQL parser rather
than keyword matching: `SELECT 'drop table'` passes, and a DELETE hidden inside
a CTE does not. A query is accepted only if:

  - it is exactly ONE statement;
  - that statement is a query (SELECT / WITH ... SELECT / UNION ...);
  - nothing inside it writes, changes the schema or talks to the engine
    (INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, PRAGMA, ATTACH, SELECT INTO ...);
  - it reads only the business tables (so no peeking at sqlite_master);
  - it calls no dangerous function (load_extension, ...).

Layer 2 (app/db/executor.py) enforces read-only inside SQLite itself, so even
a gap in this module could not change data. The two layers are deliberate.
"""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class UnsafeSQLError(ValueError):
    """The query is syntactically fine but not allowed (writes, unknown tables...).
    Not retried: refusing is the correct outcome."""


class InvalidSQLError(ValueError):
    """The query does not parse. Worth one retry with the error message."""


# Statement / clause types that must never appear anywhere in the tree.
FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Pragma, exp.Attach, exp.Detach, exp.Command, exp.Transaction,
    exp.Commit, exp.Rollback, exp.Set, exp.Use, exp.Copy, exp.LoadData, exp.Into,
)

FORBIDDEN_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "zeroblob", "randomblob"}


def validate_select(sql: str, allowed_tables: set[str]) -> str:
    """Return the query (trailing semicolon removed) if it is safe; raise otherwise."""
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise InvalidSQLError("The query is empty.")

    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except ParseError as exc:
        raise InvalidSQLError(f"The query could not be parsed: {exc}") from exc

    if len(statements) != 1:
        raise UnsafeSQLError(f"Exactly one statement is allowed, got {len(statements)}.")
    tree = statements[0]

    if not isinstance(tree, exp.Query):
        raise UnsafeSQLError(f"Only read queries (SELECT) are allowed, got {type(tree).__name__.upper()}.")

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise UnsafeSQLError(f"{type(node).__name__.upper()} is not allowed in a read-only query.")
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name in FORBIDDEN_FUNCTIONS:
                raise UnsafeSQLError(f"The function {name}() is not allowed.")

    # Names defined by WITH (CTEs) are fine to select from; everything else
    # must be one of the business tables, in the main database.
    cte_names = {cte.alias.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name, schema = table.name.lower(), table.db.lower()
        if schema not in ("", "main"):
            raise UnsafeSQLError(f"Access to database {schema!r} is not allowed.")
        if name not in allowed_tables and name not in cte_names:
            raise UnsafeSQLError(f"Unknown or forbidden table {name!r}. Allowed: {', '.join(sorted(allowed_tables))}.")

    return sql
