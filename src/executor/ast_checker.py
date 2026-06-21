"""SQL AST checker: sqlglot-based validation before execution.

Validates:
    - No DDL (CREATE/DROP/ALTER)
    - No DML (INSERT/UPDATE/DELETE/TRUNCATE)
    - No system schema access (pg_catalog, information_schema)
    - No sensitive field references
    - No CALL/DO/EXECUTE
"""

from __future__ import annotations

from typing import Any


class ASTChecker:
    """Validates SQL safety via sqlglot AST parsing + keyword deny-list."""

    def __init__(self, config: Any = None) -> None:
        self._forbidden_keywords: set[str] = set()
        self._sensitive_fields: set[str] = set()
        self._system_schemas: set[str] = set()

        if config is not None:
            self._forbidden_keywords = {kw.upper() for kw in config.security.forbidden_keywords_sql}
            self._sensitive_fields = set(config.security.sensitive_fields)
            self._system_schemas = set(config.security.pg_system_schemas)

    def check(self, sql: str) -> tuple[bool, str]:
        """Check if SQL is safe to execute.

        Args:
            sql: The SQL string to validate.

        Returns:
            (is_safe, error_message). If safe, error_message is empty.
        """
        if not sql or not sql.strip():
            return (False, "Empty SQL statement")

        sql_upper = sql.upper().strip()

        # Check 1: Forbidden keywords
        for keyword in self._forbidden_keywords:
            # Use word-boundary matching to avoid false positives
            # (e.g., "CREATE" not matching "CREATE_AT")
            if _word_in_sql(sql_upper, keyword):
                return (False, f"Forbidden SQL keyword detected: {keyword}")

        # Check 2: System schema access
        for schema in self._system_schemas:
            if schema.lower() in sql.lower():
                return (False, f"Access to system schema forbidden: {schema}")

        # Check 3: Sensitive fields (simple string match)
        for field in self._sensitive_fields:
            if field.lower() in sql.lower():
                return (False, f"Query references sensitive field: {field}")

        # Check 4: Only SELECT allowed
        sql_stripped = sql_upper.strip().lstrip("(")
        starts_with_select = (
            sql_stripped.startswith("SELECT") or
            sql_stripped.startswith("WITH")
        )
        if not starts_with_select:
            return (False, "Only SELECT and WITH (CTE) statements are allowed")

        # Check 5: Try sqlglot parse (best-effort)
        try:
            import sqlglot
            parsed = sqlglot.parse(sql, read="postgres")
            if parsed and len(parsed) > 0:
                for statement in parsed:
                    if statement is None:
                        return (False, "Unable to parse SQL statement")
        except ImportError:
            pass  # sqlglot not available — skip AST check
        except Exception:
            pass  # Parse error — let the DB catch it

        return (True, "")


def _word_in_sql(sql_upper: str, keyword: str) -> bool:
    """Check if keyword appears as a whole word in SQL.

    Avoids matching substrings (e.g., 'ALTER' in 'ALTERED').
    """
    import re
    pattern = r'\b' + re.escape(keyword) + r'\b'
    return bool(re.search(pattern, sql_upper))
