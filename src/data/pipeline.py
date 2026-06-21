"""Data pipeline orchestrator.

End-to-end: download Olist → map schema → Faker augment → inject noise → load DB.

Usage:
    python -c "from src.data.pipeline import run_pipeline; run_pipeline()"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.config import load_config, AppConfig
from src.core.logging import get_logger

logger = get_logger(__name__, component="data_pipeline")


def run_pipeline(
    data_dir: str | Path | None = None,
    config: AppConfig | None = None,
    skip_db: bool = False,
    seed: int = 42,
) -> dict[str, int]:
    """Run the complete data pipeline.

    Steps:
        1. Load Olist CSVs → raw DataFrames
        2. Map to target 12-table schema
        3. Faker augmentation (CN reviews, tickets, page_views, etc.)
        4. Inject production noise (soft_delete, UTC, enum codes, amount ambiguity)
        5. Load into PostgreSQL (if not skip_db)
        6. Setup readonly role (if not skip_db)

    Args:
        data_dir: Directory containing Olist CSVs.
        config: AppConfig instance.
        skip_db: If True, skip DB loading (DataFrames only).
        seed: Random seed for reproducibility.

    Returns:
        Dict of table_name → row_count after loading.
    """
    if config is None:
        config = load_config()

    logger.info("step_1_loading_olist", data_dir=str(data_dir))

    # Step 1 & 2: Load and map
    from src.data.olist_loader import load_olist_csvs, map_to_target_schema

    raw_dfs = load_olist_csvs(data_dir)
    target_dfs = map_to_target_schema(raw_dfs)
    logger.info(
        "olist_mapped",
        tables=len(target_dfs),
        total_rows=sum(len(df) for df in target_dfs.values()),
    )

    # Step 3: Faker augmentation
    from src.data.faker_augment import augment_all

    target_dfs = augment_all(target_dfs, seed=seed)
    logger.info(
        "faker_augmented",
        tables=len(target_dfs),
        total_rows=sum(len(df) for df in target_dfs.values()),
    )

    # Step 4: Noise injection
    from src.data.noise_injector import inject_all_noise

    target_dfs = inject_all_noise(target_dfs, seed=seed)
    logger.info("noise_injected", tables=len(target_dfs))

    # Print summary of injected noise
    _print_noise_summary(target_dfs)

    # Step 5 & 6: Load into PostgreSQL
    if not skip_db:
        from src.data.db_loader import DatabaseLoader

        loader = DatabaseLoader(config)
        logger.info("step_5_creating_tables")
        loader.create_tables()

        logger.info("step_6_loading_data")
        counts = loader.load_all(target_dfs)

        logger.info("step_7_setup_readonly")
        loader.setup_readonly_role()

        # Verify
        ok = loader.verify_readonly()
        logger.info("readonly_verified", ok=ok)

        actual_counts = loader.get_row_counts()
        logger.info("db_row_counts", **actual_counts)

        return actual_counts

    logger.info("pipeline_complete_df_only")
    return {name: len(df) for name, df in target_dfs.items()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_noise_summary(dfs: dict[str, Any]) -> None:
    """Print a summary of injected noise for verification."""
    import pandas as pd

    print("\n" + "=" * 60)
    print("NOISE INJECTION SUMMARY")
    print("=" * 60)

    # Soft deletes
    for table in ["orders", "order_items", "payments", "returns", "users"]:
        if table in dfs and "is_deleted" in dfs[table].columns:
            n_del = int(dfs[table]["is_deleted"].sum())
            n_tot = len(dfs[table])
            print(f"  [{table}] soft-deleted: {n_del}/{n_tot} ({100*n_del/n_tot:.1f}%)")

    # Timestamps in UTC
    for table in ["orders", "returns", "reviews"]:
        if table in dfs:
            ts_cols = [c for c in dfs[table].columns if "at" in c.lower()]
            if ts_cols:
                col = ts_cols[0]
                sample = dfs[table][col].dropna().iloc[0] if len(dfs[table]) > 0 else "N/A"
                print(f"  [{table}] sample timestamp ({col}): {sample} (should be naive UTC)")

    # Order status codes
    if "orders" in dfs and "order_status" in dfs["orders"].columns:
        codes = dfs["orders"]["order_status"].value_counts().to_dict()
        print(f"  [orders] status codes: {codes}")

    # Amount gap
    if "orders" in dfs and "payments" in dfs:
        o_total = dfs["orders"]["amount"].sum() if "amount" in dfs["orders"].columns else 0
        p_total = dfs["payments"]["amount"].sum() if "amount" in dfs["payments"].columns else 0
        if o_total > 0 and p_total > 0:
            gap_pct = abs(o_total - p_total) / o_total * 100
            print(f"  [amount gap] orders={o_total:,.0f} vs payments={p_total:,.0f} ({gap_pct:.1f}%)")

    print("=" * 60 + "\n")
