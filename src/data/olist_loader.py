"""Olist Brazilian E-Commerce dataset loader.

Downloads (or loads from cache) the 9 Olist CSV files and maps them
to our target 12-table schema as pandas DataFrames.

Olist source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

The 9 Olist CSVs:
    olist_customers_dataset.csv
    olist_geolocation_dataset.csv
    olist_order_items_dataset.csv
    olist_order_payments_dataset.csv
    olist_order_reviews_dataset.csv
    olist_orders_dataset.csv
    olist_products_dataset.csv
    olist_sellers_dataset.csv
    product_category_name_translation.csv
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

# Olist dataset URL (Kaggle-hosted; requires kagglehub or manual download)
OLIST_KAGGLE = "olistbr/brazilian-ecommerce"

# Expected CSV files and their column renames for our target schema
# We don't use sellers/geolocation directly in the 12-table target schema,
# but we keep them for reference / potential augmentation.

# Maps Olist CSV filename → (target table name, column renames)
OLIST_FILE_MAPPING: dict[str, tuple[str, dict[str, str]]] = {
    "olist_customers_dataset.csv": (
        "users",
        {
            "customer_id": "user_id",
            "customer_unique_id": "user_unique_id",
            "customer_zip_code_prefix": "zip_code_prefix",
            "customer_city": "city",
            "customer_state": "state",
        },
    ),
    "olist_orders_dataset.csv": (
        "orders",
        {
            "order_id": "order_id",
            "customer_id": "user_id",
            "order_status": "order_status_raw",  # We'll map to dim_order_status
            "order_purchase_timestamp": "created_at",
            "order_delivered_carrier_date": None,  # skip
            "order_delivered_customer_date": "delivered_at",
            "order_estimated_delivery_date": "estimated_delivery_date",
        },
    ),
    "olist_order_items_dataset.csv": (
        "order_items",
        {
            "order_id": "order_id",
            "order_item_id": None,  # auto-generated
            "product_id": "sku_id",
            "price": "unit_price",
            "freight_value": "freight_value",
        },
    ),
    "olist_order_payments_dataset.csv": (
        "payments",
        {
            "order_id": "order_id",
            "payment_sequential": "payment_sequential",
            "payment_type": "payment_type",
            "payment_installments": "payment_installments",
            "payment_value": "amount",
        },
    ),
    "olist_order_reviews_dataset.csv": (
        "reviews",
        {
            "review_id": "review_id",
            "order_id": "order_id",
            "review_score": "review_score",
            "review_comment_title": "review_title",
            "review_comment_message": "review_text",
            "review_creation_date": "created_at",
        },
    ),
    "olist_products_dataset.csv": (
        "skus",
        {
            "product_id": "sku_id",
            "product_category_name": "category_name",  # Keep for FK mapping
            "product_name_lenght": None,
            "product_description_lenght": None,
            "product_photos_qty": None,
            "product_weight_g": "weight_g",
            "product_length_cm": "length_cm",
            "product_height_cm": "height_cm",
            "product_width_cm": "width_cm",
        },
    ),
    "product_category_name_translation.csv": (
        "categories",
        {
            "product_category_name": "category_name",
            "product_category_name_english": "category_name_en",
        },
    ),
}


def _project_data_dir() -> Path:
    """Return the project data/raw directory."""
    root = Path(__file__).resolve().parent.parent.parent
    return root / "data" / "raw"


def load_olist_csvs(data_dir: str | Path | None = None) -> dict[str, pd.DataFrame]:
    """Load all Olist CSV files into DataFrames.

    Args:
        data_dir: Directory containing the Olist CSVs. If None, uses
                  {project_root}/data/raw/

    Returns:
        Dict mapping Olist CSV basename → DataFrame.
    """
    if data_dir is None:
        data_dir = _project_data_dir()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    dfs: dict[str, pd.DataFrame] = {}
    missing: list[str] = []

    for filename in OLIST_FILE_MAPPING:
        fpath = data_dir / filename
        if fpath.exists():
            dfs[filename] = pd.read_csv(fpath)
        else:
            missing.append(filename)

    if missing:
        raise FileNotFoundError(
            f"Missing Olist CSV files in {data_dir}:\n  "
            + "\n  ".join(missing)
            + f"\n\nDownload from Kaggle: kaggle datasets download -d {OLIST_KAGGLE}"
            + f"\nUnzip into: {data_dir}"
        )

    return dfs


def map_to_target_schema(
    raw_dfs: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Map raw Olist DataFrames to our target 12-table schema.

    Args:
        raw_dfs: Dict of Olist CSV filename → DataFrame.

    Returns:
        Dict of target table name → DataFrame with renamed columns.
    """
    target: dict[str, pd.DataFrame] = {}

    for filename, (table_name, column_map) in OLIST_FILE_MAPPING.items():
        df = raw_dfs[filename].copy()

        # Build rename dict (skip None values — columns we drop)
        rename: dict[str, str] = {}
        drop_cols: list[str] = []
        for old_col, new_col in column_map.items():
            if old_col not in df.columns:
                continue
            if new_col is None:
                drop_cols.append(old_col)
            else:
                rename[old_col] = new_col

        df = df.rename(columns=rename)
        if drop_cols:
            df = df.drop(columns=drop_cols, errors="ignore")

        if table_name in target:
            # Merge: same target table from multiple Olist files
            target[table_name] = pd.concat(
                [target[table_name], df], ignore_index=True
            )
        else:
            target[table_name] = df

    # --- Post-processing per table ---

    # orders: convert created_at to UTC timestamp, add is_deleted
    if "orders" in target:
        df = target["orders"]
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        df["delivered_at"] = pd.to_datetime(df["delivered_at"], utc=True)
        df["estimated_delivery_date"] = pd.to_datetime(
            df["estimated_delivery_date"], utc=True
        )
        # Map Olist order_status strings to our dim_order_status codes
        status_map = {
            "delivered": 1,
            "shipped": 2,
            "canceled": 3,   # Olist uses "canceled" (one L)
            "cancelled": 3,
            "processing": 4,
            "approved": 4,   # map to processing
            "invoiced": 2,   # map to shipped
            "created": 4,
            "unavailable": 3,
        }
        df["order_status"] = (
            df["order_status_raw"]
            .map(status_map)
            .fillna(4)
            .astype(int)
        )
        df = df.drop(columns=["order_status_raw"])
        target["orders"] = df

    # order_items: generate a synthetic quantity if missing (Olist doesn't have it)
    if "order_items" in target:
        df = target["order_items"]
        if "quantity" not in df.columns:
            import numpy as np
            rng = np.random.default_rng(42)
            df["quantity"] = rng.integers(1, 4, size=len(df))
        target["order_items"] = df

    # reviews: handle timestamps
    if "reviews" in target:
        df = target["reviews"]
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
        # Map sku_id from order_items (reviews in Olist are at order level)
        target["reviews"] = df

    # skus: map category_id from categories
    if "skus" in target and "categories" in target:
        df = target["skus"]
        cat_df = target["categories"]
        # Olist products.csv uses product_category_name (Portuguese)
        # We need to join through the translation table later;
        # for now, just keep the category_name in skus for the mapping
        target["skus"] = df

    # payments: no special processing needed
    # categories: deduplicate
    if "categories" in target:
        target["categories"] = target["categories"].drop_duplicates(
            subset=["category_name"]
        ).reset_index(drop=True)

    return target


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def get_target_dataframes(data_dir: str | Path | None = None) -> dict[str, pd.DataFrame]:
    """One-stop: load Olist CSVs and map to target schema.

    Returns dict of table_name → DataFrame.
    """
    raw = load_olist_csvs(data_dir)
    return map_to_target_schema(raw)
