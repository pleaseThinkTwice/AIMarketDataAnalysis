"""Tests for the SQL AST checker (deterministic, no DB needed)."""

import pytest
from src.executor.ast_checker import ASTChecker


@pytest.fixture
def checker(sample_config):
    return ASTChecker(sample_config)


class TestASTChecker:
    """Test the AST checker's security validation."""

    def test_accepts_simple_select(self, checker):
        ok, err = checker.check("SELECT * FROM orders")
        assert ok, f"Simple SELECT rejected: {err}"

    def test_accepts_select_with_where(self, checker):
        ok, err = checker.check(
            "SELECT order_id, amount FROM orders WHERE is_deleted = 0"
        )
        assert ok, f"SELECT with WHERE rejected: {err}"

    def test_accepts_cte(self, checker):
        ok, err = checker.check(
            "WITH ranked AS (SELECT *, ROW_NUMBER() OVER (ORDER BY amount DESC) AS rn FROM orders) SELECT * FROM ranked WHERE rn <= 10"
        )
        assert ok, f"CTE rejected: {err}"

    def test_rejects_drop(self, checker):
        ok, err = checker.check("DROP TABLE orders")
        assert not ok, "DROP should be rejected"

    def test_rejects_insert(self, checker):
        ok, err = checker.check("INSERT INTO orders VALUES (1, 'test')")
        assert not ok, "INSERT should be rejected"

    def test_rejects_update(self, checker):
        ok, err = checker.check("UPDATE orders SET amount = 0")
        assert not ok, "UPDATE should be rejected"

    def test_rejects_delete(self, checker):
        ok, err = checker.check("DELETE FROM orders WHERE order_id = 'x'")
        assert not ok, "DELETE should be rejected"

    def test_rejects_create(self, checker):
        ok, err = checker.check("CREATE TABLE test (id INT)")
        assert not ok, "CREATE should be rejected"

    def test_rejects_alter(self, checker):
        ok, err = checker.check("ALTER TABLE orders ADD COLUMN test INT")
        assert not ok, "ALTER should be rejected"

    def test_rejects_truncate(self, checker):
        ok, err = checker.check("TRUNCATE TABLE orders")
        assert not ok, "TRUNCATE should be rejected"

    def test_rejects_system_schema(self, checker):
        ok, err = checker.check("SELECT * FROM pg_catalog.pg_tables")
        assert not ok, "System schema access should be rejected"

    def test_rejects_sensitive_field(self, checker):
        ok, err = checker.check("SELECT phone FROM users")
        assert not ok, "Sensitive field query should be rejected"

    def test_rejects_empty_sql(self, checker):
        ok, err = checker.check("")
        assert not ok, "Empty SQL should be rejected"

    def test_rejects_grant(self, checker):
        ok, err = checker.check("GRANT SELECT ON orders TO someone")
        assert not ok, "GRANT should be rejected"

    def test_accepts_join(self, checker):
        ok, err = checker.check(
            "SELECT o.order_id, u.city FROM orders o JOIN users u ON o.user_id = u.user_id"
        )
        assert ok, f"JOIN query rejected: {err}"
