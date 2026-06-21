"""Faker-based augmentation to fill gaps in the Olist dataset.

Olist is missing:
    - Chinese review text (reviews are Portuguese-only or empty)
    - Customer service tickets table (doesn't exist in Olist)
    - Page views table (doesn't exist)
    - Add-to-cart events (doesn't exist)
    - Chinese product names
    - Return reasons (needs Chinese labels)
    - Amount column for orders (Olist doesn't provide gross amount)

We use the `Faker` library to generate realistic synthetic data that
complements the real Olist data.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from faker import Faker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_faker(locale: str = "zh_CN") -> Faker:
    """Get a Faker instance with the given locale, falling back to en_US."""
    try:
        return Faker(locale)
    except AttributeError:
        return Faker("en_US")


# ---------------------------------------------------------------------------
# Augmentation functions (operate on target DataFrames)
# ---------------------------------------------------------------------------


def augment_reviews(
    df: pd.DataFrame,
    seed: int = 42,
) -> pd.DataFrame:
    """Augment reviews with Chinese text for empty/missing review_text fields.

    Also generates Chinese review_titles where missing.
    Preserves existing Portuguese reviews.
    """
    fake_cn = _ensure_faker("zh_CN")
    rng = np.random.default_rng(seed)

    df = df.copy()

    # Fill missing review_text with Chinese
    mask_empty = df["review_text"].isna() | (df["review_text"].astype(str).str.strip() == "")
    n_empty = mask_empty.sum()
    if n_empty > 0:
        texts = [fake_cn.text(max_nb_chars=200) for _ in range(n_empty)]
        df.loc[mask_empty, "review_text"] = texts

    # Fill missing review_title
    mask_no_title = df["review_title"].isna() | (df["review_title"].astype(str).str.strip() == "")
    n_no_title = mask_no_title.sum()
    if n_no_title > 0:
        titles = [fake_cn.sentence()[:100] for _ in range(n_no_title)]
        df.loc[mask_no_title, "review_title"] = titles

    # Add user_id to reviews (Olist reviews don't have explicit user_id)
    if "user_id" not in df.columns:
        # We'll cross-reference from orders during pipeline assembly
        pass

    return df


def augment_skus(
    skus_df: pd.DataFrame,
    categories_df: pd.DataFrame,
    seed: int = 42,
) -> pd.DataFrame:
    """Add Chinese product names and assign category_id FK.

    Args:
        skus_df: SKUs DataFrame with sku_id, weight_g, etc.
        categories_df: Categories DataFrame with category_id, category_name.
    """
    fake_cn = _ensure_faker("zh_CN")
    rng = np.random.default_rng(seed)

    skus_df = skus_df.copy()

    # Generate Chinese product names based on category
    # For simplicity, use Faker catch phrases
    skus_df["product_name_cn"] = [
        fake_cn.catch_phrase() for _ in range(len(skus_df))
    ]

    # Generate price if missing (Olist uses order_items.price, not product.price)
    if "price" not in skus_df.columns or skus_df["price"].isna().all():
        skus_df["price"] = rng.uniform(5.0, 500.0, size=len(skus_df)).round(2)

    # Assign category_id FK — Olist products use category_name (Portuguese)
    # Map via the categories table: product_category_name → category_id
    if "category_name" in skus_df.columns and "category_id" in categories_df.columns:
        # Build lookup: category_name → category_id
        cat_lookup = dict(zip(categories_df["category_name"], categories_df["category_id"]))
        skus_df["category_id"] = skus_df["category_name"].map(cat_lookup)
        # For unmatched, assign a default category_id (1)
        skus_df["category_id"] = skus_df["category_id"].fillna(1).astype(int)

    # Drop the raw category_name column (we use category_id FK now)
    skus_df = skus_df.drop(columns=["category_name"], errors="ignore")

    return skus_df


def generate_customer_service_tickets(
    users_df: pd.DataFrame,
    orders_df: pd.DataFrame,
    n_tickets: int = 5_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic customer service tickets.

    Args:
        users_df: Users DataFrame.
        orders_df: Orders DataFrame (to reference real orders).
        n_tickets: Number of tickets to generate.
    """
    fake_cn = _ensure_faker("zh_CN")
    rng = np.random.default_rng(seed)

    user_ids = users_df["user_id"].values
    order_ids = orders_df["order_id"].values

    ticket_types = ["complaint", "inquiry", "return_request", "refund"]
    ticket_weights = [0.30, 0.25, 0.30, 0.15]
    ticket_statuses = ["open", "in_progress", "resolved", "closed"]
    status_weights = [0.10, 0.20, 0.50, 0.20]

    # Generate tickets
    tickets = []
    for i in range(n_tickets):
        ttype = rng.choice(ticket_types, p=ticket_weights)
        status = rng.choice(ticket_statuses, p=status_weights)
        user_id = rng.choice(user_ids)
        # ~60% of tickets reference an order
        order_id = rng.choice(order_ids) if rng.random() < 0.6 else None

        created = pd.Timestamp("2017-01-01") + pd.Timedelta(
            days=int(rng.uniform(0, 700))
        )
        resolved = None
        if status in ("resolved", "closed"):
            resolved = created + pd.Timedelta(days=int(rng.uniform(1, 14)))

        # Generate context-aware subject
        if ttype == "complaint":
            subject = fake_cn.sentence()[:80]
        elif ttype == "inquiry":
            subject = fake_cn.sentence()[:80]
        elif ttype == "return_request":
            subject = fake_cn.sentence()[:80]
        else:
            subject = fake_cn.sentence()[:80]

        tickets.append({
            "ticket_id": f"TKT_{i:06d}",
            "user_id": user_id,
            "order_id": order_id,
            "ticket_type": ttype,
            "ticket_status": status,
            "subject": subject,
            "body": fake_cn.paragraph(nb_sentences=3),
            "created_at": created,
            "resolved_at": resolved,
        })

    return pd.DataFrame(tickets)


def generate_page_views(
    users_df: pd.DataFrame,
    skus_df: pd.DataFrame,
    n_views: int = 500_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic page view events with realistic session patterns.

    Uses a power-law distribution for per-user view counts
    and realistic referrer URLs.
    """
    fake = _ensure_faker("en_US")
    rng = np.random.default_rng(seed)

    user_ids = users_df["user_id"].values
    sku_ids = skus_df["sku_id"].values

    page_types = ["homepage", "product", "search", "category", "cart"]
    page_weights = [0.15, 0.50, 0.20, 0.10, 0.05]
    referrers = [
        "google.com", "instagram.com", "facebook.com",
        "direct", "email", "youtube.com", "whatsapp",
    ]
    referrer_weights = [0.40, 0.15, 0.15, 0.15, 0.05, 0.05, 0.05]

    # Power-law distribution of views per user
    n_users = len(user_ids)
    views_per_user = rng.zipf(1.5, size=n_users)
    views_per_user = np.clip(views_per_user, 1, 500)
    # Scale to match target total views
    scale_factor = n_views / views_per_user.sum()
    views_per_user = (views_per_user * scale_factor).astype(int)
    views_per_user = np.clip(views_per_user, 1, None)

    # Generate views
    records = []
    base_date = pd.Timestamp("2016-10-01", tz="UTC")

    for user_idx, n_v in enumerate(views_per_user):
        if n_v <= 0:
            continue
        user_id = user_ids[user_idx]
        for _ in range(n_v):
            # Sessions: a user might have multiple sessions
            sku_id = rng.choice(sku_ids) if rng.random() < 0.7 else None
            page_type = rng.choice(page_types, p=page_weights)
            referrer = rng.choice(referrers, p=referrer_weights)

            # Timestamp: spread over ~700 days with session clustering
            day_offset = int(rng.uniform(0, 700))
            second_offset = int(rng.uniform(0, 86400))
            viewed_at = base_date + pd.Timedelta(days=day_offset, seconds=second_offset)

            records.append({
                "user_id": user_id,
                "sku_id": sku_id,
                "page_type": page_type,
                "referral_source": referrer,
                "session_id": f"SESSION_{user_idx}_{rng.integers(0, 100):04d}",
                "viewed_at": viewed_at,
            })

            if len(records) >= n_views:
                break
        if len(records) >= n_views:
            break

    return pd.DataFrame(records)


def generate_add_to_cart(
    users_df: pd.DataFrame,
    skus_df: pd.DataFrame,
    n_events: int = 80_000,
    conversion_rate: float = 0.08,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic add-to-cart events.

    Args:
        conversion_rate: Fraction of cart events that convert to an order
                         (matches Olist's ~8% observed conversion).
    """
    rng = np.random.default_rng(seed)

    user_ids = users_df["user_id"].values
    sku_ids = skus_df["sku_id"].values
    n_skus = len(sku_ids)

    base_date = pd.Timestamp("2016-10-01", tz="UTC")

    # Heavy-tail product popularity
    sku_probs = rng.zipf(1.3, size=n_skus).astype(float)
    sku_probs /= sku_probs.sum()

    records = []
    for _ in range(n_events):
        user_id = rng.choice(user_ids)
        sku_id = rng.choice(sku_ids, p=sku_probs)
        qty = int(rng.integers(1, 4))
        converted = rng.random() < conversion_rate

        day_offset = int(rng.uniform(0, 700))
        added_at = base_date + pd.Timedelta(
            days=day_offset, seconds=int(rng.uniform(0, 86400))
        )

        records.append({
            "user_id": user_id,
            "sku_id": sku_id,
            "quantity": qty,
            "added_at": added_at,
            "converted_to_order": converted,
        })

    return pd.DataFrame(records)


def generate_dim_order_status() -> pd.DataFrame:
    """Generate the dim_order_status dimension table."""
    return pd.DataFrame([
        {"status_code": 1, "status_name": "delivered", "status_name_cn": "已交付"},
        {"status_code": 2, "status_name": "shipped", "status_name_cn": "已发货"},
        {"status_code": 3, "status_name": "cancelled", "status_name_cn": "已取消"},
        {"status_code": 4, "status_name": "processing", "status_name_cn": "处理中"},
    ])


def generate_return_reasons(seed: int = 42) -> pd.DataFrame:
    """Generate the return_reasons dictionary with Chinese labels."""
    reasons = [
        ("DEFECT", "Defective product", "产品缺陷"),
        ("WRONG_SIZE", "Wrong size / does not fit", "尺码不合适"),
        ("WRONG_ITEM", "Wrong item sent", "发错商品"),
        ("NOT_AS_DESCRIBED", "Product not as described", "与描述不符"),
        ("DAMAGED_IN_TRANSPORT", "Damaged during transport", "运输中损坏"),
        ("LATE_DELIVERY", "Late delivery", "配送延迟"),
        ("CHANGE_OF_MIND", "Customer changed mind", "客户改变主意"),
        ("DUPLICATE_ORDER", "Duplicate order", "重复下单"),
        ("QUALITY_ISSUE", "Quality not satisfactory", "质量不满意"),
        ("OTHER", "Other reason", "其他原因"),
    ]
    return pd.DataFrame(
        [
            {"reason_code": code, "reason_name": name, "reason_name_cn": cn}
            for code, name, cn in reasons
        ]
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def augment_all(
    target_dfs: dict[str, pd.DataFrame],
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """Run all augmentation steps on the target DataFrames.

    Args:
        target_dfs: Dict of table_name → DataFrame from olist_loader.
        seed: Random seed for reproducibility.

    Returns:
        Augmented dict of table_name → DataFrame.
    """
    dfs = {k: v.copy() for k, v in target_dfs.items()}

    # 0. Fix categories — assign sequential IDs FIRST (needed by SKU mapping)
    if "categories" in dfs:
        cat_df = dfs["categories"]
        if "category_id" not in cat_df.columns:
            cat_df["category_id"] = range(1, len(cat_df) + 1)
            dfs["categories"] = cat_df

    # 1. Augment reviews with Chinese text
    if "reviews" in dfs:
        dfs["reviews"] = augment_reviews(dfs["reviews"], seed=seed)

    # 2. Augment SKUs with Chinese names + category_id FK mapping
    if "skus" in dfs and "categories" in dfs:
        dfs["skus"] = augment_skus(dfs["skus"], dfs["categories"], seed=seed)

    # 3. Generate return reasons dictionary
    dfs["return_reasons"] = generate_return_reasons(seed=seed)

    # 4. Generate customer service tickets
    if "users" in dfs and "orders" in dfs:
        dfs["customer_service_tickets"] = generate_customer_service_tickets(
            dfs["users"], dfs["orders"], seed=seed,
        )

    # 5. Generate page views
    if "users" in dfs and "skus" in dfs:
        dfs["page_views"] = generate_page_views(
            dfs["users"], dfs["skus"], seed=seed,
        )

    # 6. Generate add-to-cart events
    if "users" in dfs and "skus" in dfs:
        dfs["add_to_cart"] = generate_add_to_cart(
            dfs["users"], dfs["skus"], seed=seed,
        )

    # 7. Generate dim_order_status
    dfs["dim_order_status"] = generate_dim_order_status()

    return dfs
