"""SQLite-based sandbox executor — zero-dependency alternative to PostgreSQL.

Allows the agent to run end-to-end without Docker or PostgreSQL.
Translates PostgreSQL SQL to SQLite-compatible SQL on the fly.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from src.core.schemas import ExecutionResult, ExecutionStatus, ErrorClass
from src.correction.classifier import ErrorClassifier


class SQLiteSandbox:
    """SQLite-based sandbox that mirrors the PostgreSQL SandboxExecutor API.

    Loads CSV data directly into SQLite tables and executes generated SQL
    with PostgreSQL→SQLite dialect translation.
    """

    def __init__(self, config: Any = None) -> None:
        self._db_path = Path("data/sandbox.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._max_rows = config.sandbox.limits.max_rows if config else 100_000

    # ------------------------------------------------------------------
    # Data loading from pipeline DataFrames
    # ------------------------------------------------------------------

    def load_from_pipeline(self) -> dict[str, int]:
        """Run the data pipeline and load all DataFrames into SQLite.

        Returns:
            Dict of table_name → row_count.
        """
        from src.data.olist_loader import load_olist_csvs, map_to_target_schema
        from src.data.faker_augment import augment_all
        from src.data.noise_injector import inject_all_noise

        # Run pipeline steps manually to get DataFrames
        raw = load_olist_csvs()
        target = map_to_target_schema(raw)
        augmented = augment_all(target)
        dfs = inject_all_noise(augmented)  # dict[str, DataFrame]

        conn = sqlite3.connect(str(self._db_path))
        try:
            counts: dict[str, int] = {}
            for table_name, df in dfs.items():
                df.to_sql(table_name, conn, if_exists="replace", index=False)
                counts[table_name] = len(df)
            conn.commit()
            return counts
        finally:
            conn.close()

    def is_loaded(self) -> bool:
        """Check if the SQLite DB has been loaded with data."""
        if not self._db_path.exists():
            return False
        try:
            conn = sqlite3.connect(str(self._db_path))
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            conn.close()
            return len(tables) >= 5  # At least 5 of our tables
        except Exception:
            return False

    # ------------------------------------------------------------------
    # SQL execution (mirrors SandboxExecutor.execute)
    # ------------------------------------------------------------------

    def execute(self, sql: str) -> ExecutionResult:
        """Execute a SQL statement, translating PG dialect to SQLite.

        Args:
            sql: PostgreSQL SQL (from LLM).

        Returns:
            ExecutionResult with rows, columns, etc.
        """
        # Translate PostgreSQL → SQLite
        sqlite_sql = self._translate_sql(sql)

        # Wrap with LIMIT
        if not re.search(r'LIMIT\s+\d+', sqlite_sql, re.IGNORECASE):
            sqlite_sql = f"{sqlite_sql.rstrip(';').strip()} LIMIT {self._max_rows}"

        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            try:
                cur = conn.execute(sqlite_sql)
                columns = [d[0] for d in cur.description] if cur.description else []
                rows = [list(r) for r in cur.fetchall()]
                return ExecutionResult.ok_result(
                    task_id=0, sql=sql,
                    columns=columns, rows=rows,
                )
            except sqlite3.Error as e:
                error_msg = str(e)
                error_class = ErrorClassifier.classify(error_msg)
                return ExecutionResult.error_result(
                    task_id=0, sql=sql, error=error_msg, error_class=error_class,
                )
            finally:
                conn.close()
        except Exception as e:
            return ExecutionResult.error_result(
                task_id=0, sql=sql, error=str(e), error_class=ErrorClass.UNKNOWN,
            )

    # ------------------------------------------------------------------
    # PostgreSQL → SQLite translation
    # ------------------------------------------------------------------

    def _translate_sql(self, sql: str) -> str:
        """Translate PostgreSQL-specific SQL to SQLite-compatible SQL.

        Handles:
            - ILIKE → LIKE (case-insensitive in SQLite for ASCII)
            - AT TIME ZONE → remove (SQLite stores naive timestamps)
            - DATE_TRUNC → strftime
            - CURRENT_DATE → date('now')
            - INTERVAL → sqlite3 doesn't support; approximate
            - BOOLEAN → INTEGER (0/1)
            - ::type casts → remove (SQLite is flexible)
        """
        s = sql.strip()

        # Remove PostgreSQL casts (::type)
        s = re.sub(r'::\w+(\(\d+,\d+\))?', '', s)

        # ILIKE → LIKE
        s = re.sub(r'\bILIKE\b', 'LIKE', s, flags=re.IGNORECASE)

        # CURRENT_DATE → date('now')
        s = re.sub(r'\bCURRENT_DATE\b', "date('now')", s)

        # AT TIME ZONE '...' → remove the whole clause
        s = re.sub(r"\s+AT\s+TIME\s+ZONE\s+'[^']*'", '', s, flags=re.IGNORECASE)

        # DATE_TRUNC('quarter', ...) → approximate with strftime
        s = re.sub(
            r"DATE_TRUNC\('quarter',\s*(.+?)\)",
            r"date(\1, 'start of month', printf('-%d months', (CAST(strftime('%%m', \1) AS INTEGER) - 1) %% 3))",
            s, flags=re.IGNORECASE,
        )
        # Simpler: DATE_TRUNC('month', ...) → strftime
        s = re.sub(
            r"DATE_TRUNC\('month',\s*(.+?)\)",
            r"date(\1, 'start of month')",
            s, flags=re.IGNORECASE,
        )
        # DATE_TRUNC('year', ...)
        s = re.sub(
            r"DATE_TRUNC\('year',\s*(.+?)\)",
            r"date(\1, 'start of year')",
            s, flags=re.IGNORECASE,
        )

        # INTERVAL 'N months/days' → simplified (SQLite date math)
        s = re.sub(r"-\s*INTERVAL\s*'(\d+)\s+month'", r", '-\1 months'", s, flags=re.IGNORECASE)
        s = re.sub(r"-\s*INTERVAL\s*'(\d+)\s+day'", r", '-\1 days'", s, flags=re.IGNORECASE)

        # NULLIF → IFNULL (SQLite)
        s = re.sub(r'\bNULLIF\(', 'IFNULL(', s)

        # CONCAT → || (SQLite)
        # (keep as-is, SQLite supports both)

        # Remove final semicolon for SQLite
        s = s.rstrip(";")

        return s
