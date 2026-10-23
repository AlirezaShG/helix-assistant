"""Both safety layers, tested separately: each must hold even if the other failed."""

import sqlite3

import pytest

from app.db.executor import SQLExecutionError, SQLPermissionError, list_tables, run_read_only
from app.db.sql_safety import InvalidSQLError, UnsafeSQLError, validate_select

TABLES = {"products", "customers", "orders", "order_items"}


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM orders",
    "SELECT c.city, SUM(oi.quantity * oi.unit_price) AS revenue FROM orders o "
    "JOIN customers c ON c.customer_id = o.customer_id "
    "JOIN order_items oi ON oi.order_id = o.order_id WHERE o.status = 'delivered' GROUP BY c.city;",
    "WITH monthly AS (SELECT strftime('%m', order_date) AS m, COUNT(*) AS n FROM orders GROUP BY m) "
    "SELECT * FROM monthly ORDER BY n DESC LIMIT 1",
    "SELECT name FROM products UNION SELECT name FROM customers",
    "SELECT 'drop table orders' AS harmless_text FROM products",  # keywords inside strings are fine
])
def test_accepts_read_queries(sql):
    assert validate_select(sql, TABLES)


@pytest.mark.parametrize("sql, reason", [
    ("DELETE FROM orders", "SELECT"),
    ("DROP TABLE customers", "SELECT"),
    ("UPDATE products SET unit_price = 0", "SELECT"),
    ("INSERT INTO orders VALUES (1, 1, '2026-01-01', 'delivered', 'paid')", "SELECT"),
    ("SELECT 1; DROP TABLE orders", "one statement"),
    ("PRAGMA table_info(orders)", "SELECT"),
    ("ATTACH DATABASE 'x.db' AS other", "SELECT"),
    ("SELECT * INTO backup FROM orders", "INTO"),
    ("SELECT * FROM sqlite_master", "forbidden table"),
    ("SELECT * FROM salaries", "forbidden table"),
    ("SELECT load_extension('evil.so')", "load_extension"),
    ("SELECT * FROM other.orders", "database"),
])
def test_rejects_writes_and_tricks(sql, reason):
    with pytest.raises(UnsafeSQLError, match=reason):
        validate_select(sql, TABLES)


@pytest.mark.parametrize("sql", ["", "   ;  ", "SELEC * FRM orders WHERE"])
def test_garbage_is_invalid_not_unsafe(sql):
    with pytest.raises(InvalidSQLError):
        validate_select(sql, TABLES)


def test_executor_runs_a_select(db_path):
    result = run_read_only(db_path, "SELECT COUNT(*) AS n FROM customers")
    assert result.columns == ["n"] and result.rows == [[15]]


@pytest.mark.parametrize("sql", [
    "DELETE FROM orders",
    "UPDATE products SET unit_price = 0",
    "CREATE TABLE x (a INTEGER)",
    "PRAGMA writable_schema = 1",
])
def test_executor_refuses_writes_even_without_validation(db_path, sql):
    with pytest.raises(SQLPermissionError):
        run_read_only(db_path, sql)
    # ... and the data is untouched.
    assert run_read_only(db_path, "SELECT COUNT(*) FROM orders").rows[0][0] > 0


def test_executor_refuses_multiple_statements(db_path):
    with pytest.raises(SQLExecutionError):
        run_read_only(db_path, "SELECT 1; DELETE FROM orders")


def test_executor_caps_rows(db_path):
    result = run_read_only(db_path, "SELECT * FROM order_items", max_rows=10)
    assert len(result.rows) == 10 and result.truncated


def test_executor_stops_slow_queries(db_path):
    endless = "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT COUNT(*) FROM n"
    with pytest.raises(SQLExecutionError, match="longer than"):
        run_read_only(db_path, endless, timeout_seconds=0.5)


def test_execution_errors_are_reported(db_path):
    with pytest.raises(SQLExecutionError, match="no such column"):
        run_read_only(db_path, "SELECT revenue FROM orders")


def test_seed_data_is_deterministic_and_consistent(db_path):
    assert list_tables(db_path) == TABLES
    with sqlite3.connect(db_path) as conn:
        orphan_items = conn.execute(
            "SELECT COUNT(*) FROM order_items oi LEFT JOIN orders o USING (order_id) WHERE o.order_id IS NULL"
        ).fetchone()[0]
        statuses = {s for (s,) in conn.execute("SELECT DISTINCT payment_status FROM orders WHERE status != 'delivered'")}
    assert orphan_items == 0
    assert statuses == {"not_applicable"}
