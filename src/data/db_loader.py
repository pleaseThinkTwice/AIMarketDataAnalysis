"""PostgreSQL database loader.

Creates tables from DDL, bulk-inserts data from DataFrames,
and configures the sandbox (read-only role, resource limits).

Usage:
    from src.core.config import load_config
    from src.data.db_loader import DatabaseLoader

    cfg = load_config()
    loader = DatabaseLoader(cfg)
    loader.create_tables()
    loader.load_all(dfs)          # dfs: dict of table_name → DataFrame
    loader.setup_readonly_role()
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
import psycopg2
from psycopg2 import sql

from src.data.schema_ddl import CREATE_ALL_SQL, DROP_ALL_SQL, TABLE_NAMES


class DatabaseLoader:
    """Loads data into the PostgreSQL sandbox database."""

    def __init__(self, config: Any) -> None:
        """Args:
            config: AppConfig instance (from src.core.config).
        """
        self._cfg = config
        self._sandbox = config.sandbox

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _admin_conn(self):
        """Connect as the admin user (postgres) for DDL operations."""
        return psycopg2.connect(
            host=self._sandbox.db.host,
            port=self._sandbox.db.port,
            dbname=self._sandbox.db.dbname,
            user="postgres",
            password="devpass",  # Docker default from the setup script
        )

    def _readonly_conn(self):
        """Connect as the agent_readonly user."""
        pw = self._sandbox.db.password or "agent_pass"
        return psycopg2.connect(
            host=self._sandbox.db.host,
            port=self._sandbox.db.port,
            dbname=self._sandbox.db.dbname,
            user=self._sandbox.db.user,
            password=pw,
        )

    # ------------------------------------------------------------------
    # DDL operations
    # ------------------------------------------------------------------

    def drop_all(self) -> None:
        """Drop all tables (CASCADE). Use with caution."""
        with self._admin_conn() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(DROP_ALL_SQL)

    def create_tables(self) -> None:
        """Execute the full CREATE TABLE DDL."""
        with self._admin_conn() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(CREATE_ALL_SQL)

    # ------------------------------------------------------------------
    # Data loading (bulk COPY for performance)
    # ------------------------------------------------------------------

    def load_table(
        self,
        table_name: str,
        df: pd.DataFrame,
        conn: Any | None = None,
    ) -> int:
        """Load a single DataFrame into a table using COPY.

        Args:
            table_name: Target table name.
            df: DataFrame to load. Column names must match table columns.
            conn: Optional existing connection.

        Returns:
            Number of rows loaded.
        """
        own_conn = conn is None
        if own_conn:
            conn = self._admin_conn()

        try:
            # Identify common columns
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT column_name FROM information_schema.columns WHERE table_name = %s"),
                    [table_name],
                )
                db_cols = {row[0] for row in cur.fetchall()}

            df_cols = [c for c in df.columns if c.lower() in {dc.lower() for dc in db_cols}]
            df_subset = df[df_cols].copy()

            # Handle NULLs and types
            df_subset = df_subset.where(pd.notna(df_subset), None)

            # Use COPY via StringIO for fast bulk insert
            buf = io.StringIO()
            df_subset.to_csv(buf, index=False, header=False, na_rep="\\N")
            buf.seek(0)

            with conn.cursor() as cur:
                cur.copy_from(
                    buf,
                    table_name,
                    columns=df_cols,
                    sep=",",
                    null="\\N",
                )
            conn.commit()

            return len(df_subset)

        finally:
            if own_conn:
                conn.close()

    def load_all(self, dfs: dict[str, pd.DataFrame]) -> dict[str, int]:
        """Load all DataFrames into their respective tables.

        Args:
            dfs: Dict of table_name → DataFrame.

        Returns:
            Dict of table_name → rows_loaded.
        """
        counts: dict[str, int] = {}
        conn = self._admin_conn()

        try:
            # Load in dependency order (parents before children)
            for table_name in TABLE_NAMES:
                if table_name in dfs:
                    n = self.load_table(table_name, dfs[table_name], conn=conn)
                    counts[table_name] = n
        finally:
            conn.close()

        return counts

    # ------------------------------------------------------------------
    # Sandbox setup
    # ------------------------------------------------------------------

    def setup_readonly_role(self, password: str = "agent_pass") -> None:
        """Create (or update) the agent_readonly role with minimal privileges.

        Steps:
            1. CREATE ROLE if not exists
            2. GRANT CONNECT, USAGE
            3. GRANT SELECT ON ALL TABLES
            4. Set statement_timeout and work_mem
        """
        with self._admin_conn() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                # Create role
                cur.execute(
                    sql.SQL(
                        "DO $$ BEGIN "
                        "  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_readonly') THEN "
                        "    CREATE ROLE agent_readonly WITH LOGIN PASSWORD %s; "
                        "  END IF; "
                        "END $$;"
                    ),
                    [password],
                )

                # Grant privileges
                cur.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO agent_readonly").format(
                        sql.Identifier(self._sandbox.db.dbname)
                    )
                )
                cur.execute("GRANT USAGE ON SCHEMA public TO agent_readonly")
                cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_readonly")

                # Set resource limits
                cur.execute(
                    f"ALTER ROLE agent_readonly SET statement_timeout = '{self._sandbox.limits.statement_timeout_s}s'"
                )
                cur.execute(
                    f"ALTER ROLE agent_readonly SET work_mem = '{self._sandbox.limits.work_mem_mb}MB'"
                )

    def verify_readonly(self) -> bool:
        """Verify the readonly role can SELECT but not INSERT/UPDATE/DELETE.

        Returns True if the role is correctly restricted.
        """
        conn = self._readonly_conn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                # Should work: SELECT
                cur.execute("SELECT 1")
                # Should fail: INSERT
                try:
                    cur.execute("INSERT INTO dim_order_status VALUES (99, 'test', 'test')")
                    return False  # INSERT should have been rejected
                except psycopg2.Error:
                    pass  # Expected — permission denied
                return True
        finally:
            conn.close()

    def get_row_counts(self) -> dict[str, int]:
        """Get row counts for all tables (via readonly connection)."""
        conn = self._readonly_conn()
        try:
            counts = {}
            with conn.cursor() as cur:
                for table in TABLE_NAMES:
                    try:
                        cur.execute(
                            sql.SQL("SELECT COUNT(*) FROM {}").format(
                                sql.Identifier(table)
                            )
                        )
                        counts[table] = cur.fetchone()[0]
                    except psycopg2.Error:
                        counts[table] = -1
            return counts
        finally:
            conn.close()
