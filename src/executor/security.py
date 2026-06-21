"""Security pipeline: orchestrates the 5-layer defense.

1. AST check (sqlglot deny-list)
2. DB-level read-only role (handled at DB setup)
3. Resource limits (statement_timeout, work_mem)
4. Sensitive field blocking (in AST checker)
5. Injection prevention (NL2SQL itself)

Auto-detects PostgreSQL availability; falls back to SQLite for zero-dependency mode.

Usage:
    pipeline = SecurityPipeline(config)
    result = pipeline.validate_and_execute(sql)
"""

from __future__ import annotations

from typing import Any

from src.core.schemas import ExecutionResult, ExecutionStatus, ErrorClass
from src.executor.ast_checker import ASTChecker


class SecurityPipeline:
    """5-layer defense-in-depth for SQL execution."""

    def __init__(self, config: Any) -> None:
        self._cfg = config
        self._ast_checker = ASTChecker(config)
        self._sandbox = None
        self._engine = "unknown"

    def _ensure_sandbox(self) -> None:
        """Lazy-init the sandbox, trying PostgreSQL first, then SQLite."""
        if self._sandbox is not None:
            return

        # Try PostgreSQL first
        try:
            from src.executor.sandbox import SandboxExecutor
            import psycopg2
            sb = SandboxExecutor(self._cfg)
            conn = sb._get_conn()
            conn.close()
            self._sandbox = sb
            self._engine = "postgresql"
            return
        except Exception:
            pass

        # Fall back to SQLite
        try:
            from src.executor.sqlite_sandbox import SQLiteSandbox
            sb = SQLiteSandbox(self._cfg)
            # Auto-load data if needed
            if not sb.is_loaded():
                sb.load_from_pipeline()
            self._sandbox = sb
            self._engine = "sqlite"
        except Exception as e:
            raise RuntimeError(f"No database backend available: {e}")

    @property
    def engine(self) -> str:
        self._ensure_sandbox()
        return self._engine

    def validate_and_execute(self, sql: str) -> ExecutionResult:
        """Validate and execute SQL through all security layers.

        Args:
            sql: The SQL string to validate and execute.

        Returns:
            ExecutionResult with execution outcome.
        """
        # Layer 1: AST check
        safe, err = self._ast_checker.check(sql)
        if not safe:
            return ExecutionResult.error_result(
                task_id=0,
                sql=sql,
                error=f"Security rejected: {err}",
                error_class=ErrorClass.SYNTAX,
            )

        # Layer 2-5: Execute in sandbox
        self._ensure_sandbox()
        return self._sandbox.execute(sql)
