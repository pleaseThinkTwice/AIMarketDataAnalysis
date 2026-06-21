"""Inject "production noise" patterns into the clean dataset.

These are deliberately introduced to test whether the LLM Agent:
    1. Filters soft-deleted rows (is_deleted = 0)
    2. Handles UTC timestamps correctly (AT TIME ZONE conversion)
    3. JOINs to dimension tables for enum codes
    4. Uses the correct amount column (orders.amount vs payments.amount)

Each noise pattern is inspired by real production database quirks.
The patterns are applied AFTER Faker augmentation and BEFORE DB loading.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 1. Soft-delete injection
# ---------------------------------------------------------------------------

def inject_soft_deletes(
    dfs: dict[str, pd.DataFrame],
    soft_delete_ratio: float = 0.02,
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """Mark ~2% of rows as is_deleted = 1 in selected tables.

    Tables affected: orders, order_items, payments, returns, customer_service_tickets,
                     categories, skus, users.
    Tables NOT affected: page_views, add_to_cart, reviews, return_reasons, dim_order_status.
    """
    rng = np.random.default_rng(seed)
    tables_with_sd = ["orders", "order_items", "payments", "returns",
                       "customer_service_tickets", "categories", "skus", "users"]

    dfs = {k: v.copy() for k, v in dfs.items()}

    for table in tables_with_sd:
        if table not in dfs:
            continue
        df = dfs[table]
        if "is_deleted" not in df.columns:
            df["is_deleted"] = 0
        n_rows = len(df)
        n_deleted = max(1, int(n_rows * soft_delete_ratio))
        delete_indices = rng.choice(n_rows, size=n_deleted, replace=False)
        df.loc[delete_indices, "is_deleted"] = 1
        dfs[table] = df

    return dfs


# ---------------------------------------------------------------------------
# 2. UTC timestamp enforcement
# ---------------------------------------------------------------------------

def enforce_utc_timestamps(
    dfs: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Ensure all timestamp columns are stored as UTC without timezone info.

    This creates the classic "timezone trap": the data IS in UTC, but the
    schema_metadata.json notes that business "quarter" means America/Sao_Paulo.
    If the LLM forgets AT TIME ZONE conversion, quarter-boundary queries
    will be off by 3 hours (BRT = UTC-3).
    """
    dfs = {k: v.copy() for k, v in dfs.items()}

    timestamp_cols: dict[str, list[str]] = {
        "orders": ["created_at", "delivered_at", "estimated_delivery_date"],
        "returns": ["created_at"],
        "reviews": ["created_at"],
        "page_views": ["viewed_at"],
        "add_to_cart": ["added_at"],
        "customer_service_tickets": ["created_at", "resolved_at"],
    }

    for table, cols in timestamp_cols.items():
        if table not in dfs:
            continue
        df = dfs[table]
        for col in cols:
            if col in df.columns:
                # Convert to UTC, then strip timezone info (store as naive UTC)
                dt = pd.to_datetime(df[col], utc=True)
                # Store as TIMESTAMP WITHOUT TIME ZONE (naive, but UTC values)
                df[col] = dt.dt.tz_localize(None)
        dfs[table] = df

    return dfs


# ---------------------------------------------------------------------------
# 3. Enum code enforcement (order_status)
# ---------------------------------------------------------------------------

def enforce_enum_codes(
    dfs: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Ensure orders.order_status is stored as integer codes 1-4.

    This forces the LLM to JOIN dim_order_status to get human-readable labels.
    If the LLM writes `WHERE order_status = 'delivered'` instead of
    `WHERE order_status = 1`, it will get a type error (self-correction signal).
    """
    dfs = {k: v.copy() for k, v in dfs.items()}

    if "orders" in dfs:
        df = dfs["orders"]
        if "order_status" in df.columns:
            # Ensure int type
            df["order_status"] = df["order_status"].astype(int)
            # Clamp to valid range 1-4
            df["order_status"] = df["order_status"].clip(1, 4)
        dfs["orders"] = df

    return dfs


# ---------------------------------------------------------------------------
# 4. Amount ambiguity injection
# ---------------------------------------------------------------------------

def inject_amount_ambiguity(
    dfs: dict[str, pd.DataFrame],
    discount_rate: float = 0.15,
    discount_fraction: float = 0.15,
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """Create a gap between orders.amount (gross) and payments.amount (net).

    About 15% of orders have a discount that creates a gap between
    the gross amount (orders.amount) and the net paid amount (payments.amount).
    If the LLM uses the wrong column ("销售额" vs "实收"), the numbers
    will be systematically wrong — a semantic error that Critic should catch.
    """
    rng = np.random.default_rng(seed)
    dfs = {k: v.copy() for k, v in dfs.items()}

    if "orders" not in dfs:
        return dfs

    orders_df = dfs["orders"]

    # Compute orders.amount from order_items if not already present
    if "amount" not in orders_df.columns or orders_df["amount"].isna().all():
        # Sum up order_items per order
        if "order_items" in dfs:
            items = dfs["order_items"]
            # Olist: each row is an item with unit_price + freight_value
            gross_per_order = items.groupby("order_id").apply(
                lambda g: (g["unit_price"] * g.get("quantity", 1)).sum()
                + g["freight_value"].sum()
            )
            orders_df["amount"] = orders_df["order_id"].map(gross_per_order)
            median_amount = orders_df["amount"].median() if orders_df["amount"].notna().any() else 100.0
            orders_df["amount"] = orders_df["amount"].fillna(median_amount).round(2)

    # Inject discounts on ~15% of orders
    n_orders = len(orders_df)
    n_discounted = int(n_orders * discount_fraction)
    discount_indices = rng.choice(n_orders, size=n_discounted, replace=False)

    # Store gross amount (before discount)
    if "amount" in orders_df.columns:
        orders_df["amount"] = orders_df["amount"].astype(float)

    # For the discounted orders, payments should be lower
    if "payments" in dfs:
        payments_df = dfs["payments"]

        # Ensure payments.amount exists
        if "amount" not in payments_df.columns:
            payments_df["amount"] = 0.0

        # For each discounted order, reduce payment amount
        discounted_order_ids = set(orders_df.iloc[discount_indices]["order_id"])

        for order_id in discounted_order_ids:
            pmask = payments_df["order_id"] == order_id
            if pmask.any():
                # Reduce payment by 5-25%
                discount_pct = rng.uniform(0.05, discount_rate)
                payments_df.loc[pmask, "amount"] = (
                    payments_df.loc[pmask, "amount"] * (1 - discount_pct)
                )

        dfs["payments"] = payments_df

    dfs["orders"] = orders_df
    return dfs


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def inject_all_noise(
    dfs: dict[str, pd.DataFrame],
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """Apply all noise injection steps in order.

    Args:
        dfs: Dict of table_name → DataFrame (post-augmentation).
        seed: Random seed.

    Returns:
        Noise-injected dict of table_name → DataFrame.
    """
    dfs = inject_soft_deletes(dfs, seed=seed)
    dfs = enforce_utc_timestamps(dfs)
    dfs = enforce_enum_codes(dfs)
    dfs = inject_amount_ambiguity(dfs, seed=seed)
    return dfs
