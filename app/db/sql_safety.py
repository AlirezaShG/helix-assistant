"""SQL safety layer 1: validate LLM-generated SQL before it runs."""

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class UnsafeSQLError(ValueError):
    """The query is syntactically fine but not allowed (writes, unknown tables...)."""


class InvalidSQLError(ValueError):
    """The query does not parse."""


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

    cte_names = {cte.alias.lower() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        name, schema = table.name.lower(), table.db.lower()
        if schema not in ("", "main"):
            raise UnsafeSQLError(f"Access to database {schema!r} is not allowed.")
        if name not in allowed_tables and name not in cte_names:
            raise UnsafeSQLError(f"Unknown or forbidden table {name!r}. Allowed: {', '.join(sorted(allowed_tables))}.")

    return sql
