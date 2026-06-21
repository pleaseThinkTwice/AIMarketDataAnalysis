"""Sandbox executor: read-only PostgreSQL query execution.

Executes SQL against the agent_readonly role with statement_timeout and
row limits already configured at the DB role level.
"""

from __future__ import annotations

import re
from typing import Any

import psycopg2

from src.core.schemas import ExecutionResult, ExecutionStatus, ErrorClass
from src.correction.classifier import ErrorClassifier


class SandboxExecutor:
    """Executes SQL in a read-only sandboxed PostgreSQL connection."""

    def __init__(self, config: Any) -> None:
        self._cfg = config
        self._pool = None  # Lazy connection

    def _get_conn(self):
        """Get a connection to the sandbox DB as agent_readonly."""
        sb = self._cfg.sandbox
        pw = sb.db.password or "agent_pass"
        return psycopg2.connect(
            host=sb.db.host,
            port=sb.db.port,
            dbname=sb.db.dbname,
            user=sb.db.user,
            password=pw,
        )

    def execute(self, sql: str) -> ExecutionResult:
        """Execute a SELECT SQL statement.

        Args:
            sql: The SQL to execute (already validated by ASTChecker).

        Returns:
            ExecutionResult with status, columns, rows, row_count, and error (if any).
        """
        # Wrap with LIMIT if not present
        if not re.search(r'LIMIT\s+\d+', sql, re.IGNORECASE):
            max_rows = self._cfg.sandbox.limits.max_rows
            sql = f"{sql.rstrip(';').strip()} LIMIT {max_rows}"

        try:
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    columns = [desc[0] for desc in cur.description] if cur.description else []
                    rows = [list(r) for r in cur.fetchall()]
                return ExecutionResult.ok_result(
                    task_id=0,  # Will be set by caller
                    sql=sql,
                    columns=columns,
                    rows=rows,
                )
            finally:
                conn.close()
        except psycopg2.Error as e:
            error_msg = str(e).strip()
            error_class = ErrorClassifier.classify(error_msg)
            return ExecutionResult.error_result(
                task_id=0,
                sql=sql,
                error=error_msg,
                error_class=error_class,
            )
        except Exception as e:
            return ExecutionResult.error_result(
                task_id=0,
                sql=sql,
                error=str(e),
                error_class=ErrorClass.UNKNOWN,
            )
