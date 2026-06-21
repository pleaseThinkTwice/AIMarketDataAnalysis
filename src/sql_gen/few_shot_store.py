"""JSONL-based few-shot exemplar library.

Stores (task, SQL, output_shape) exemplars that grow organically
through evaluation iteration. Every gold SQL that passes execution
gets added to the library.

Usage:
    store = FewShotStore("data/exemplars.jsonl")
    store.add(task_text="...", sql="...", output_shape="...")
    examples = store.list_all()
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.core.schemas import FewShotExample


class FewShotStore:
    """CRUD interface for the few-shot exemplar library."""

    def __init__(self, filepath: str = "data/exemplars.jsonl") -> None:
        self._filepath = Path(filepath)
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        if not self._filepath.exists():
            self._filepath.touch()

    def add(
        self,
        task_text: str,
        sql: str,
        output_shape: str = "",
        tags: list[str] | None = None,
    ) -> None:
        """Add a new exemplar to the library."""
        example = FewShotExample(
            task_text=task_text,
            sql=sql,
            output_shape=output_shape,
            tags=tags or [],
        )
        with open(self._filepath, "a", encoding="utf-8") as fh:
            fh.write(example.model_dump_json() + "\n")

    def list_all(self) -> list[FewShotExample]:
        """Return all exemplars in the library."""
        examples: list[FewShotExample] = []
        if not self._filepath.exists():
            return examples
        with open(self._filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    examples.append(FewShotExample.model_validate_json(line))
                except Exception:
                    continue
        return examples

    def count(self) -> int:
        """Return the number of exemplars."""
        if not self._filepath.exists():
            return 0
        count = 0
        with open(self._filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    count += 1
        return count

    def seed_with_defaults(self, dialect: str = "postgresql") -> None:
        """Seed the library with a minimal set of hand-written exemplars.

        These cover the most common SQL patterns for e-commerce analysis.
        """
        if self.count() > 0:
            return  # Already seeded

        seeds = [
            {
                "task_text": "统计每个品类的订单数量，按订单数降序",
                "sql": "SELECT c.category_name, COUNT(o.order_id) AS order_count "
                       "FROM orders o JOIN order_items oi ON o.order_id = oi.order_id "
                       "JOIN skus s ON oi.sku_id = s.sku_id "
                       "JOIN categories c ON s.category_id = c.category_id "
                       "WHERE o.is_deleted = 0 AND c.is_deleted = 0 "
                       "GROUP BY c.category_name ORDER BY order_count DESC LIMIT 20",
                "output_shape": "N行2列，品类名+订单数",
                "tags": ["aggregation", "join", "group_by"],
            },
            {
                "task_text": "查询上个月销售额最高的10个商品",
                "sql": "SELECT s.sku_id, s.product_name_cn, SUM(oi.unit_price * oi.quantity) AS revenue "
                       "FROM order_items oi JOIN orders o ON oi.order_id = o.order_id "
                       "JOIN skus s ON oi.sku_id = s.sku_id "
                       "WHERE o.created_at >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month') "
                       "AND o.created_at < DATE_TRUNC('month', CURRENT_DATE) "
                       "AND o.is_deleted = 0 AND oi.is_deleted = 0 "
                       "GROUP BY s.sku_id, s.product_name_cn ORDER BY revenue DESC LIMIT 10",
                "output_shape": "10行2列，商品+销售额",
                "tags": ["aggregation", "join", "group_by", "time_filter", "top_k"],
            },
            {
                "task_text": "计算上季度每个品类的退货率",
                "sql": "SELECT c.category_name, "
                       "COUNT(DISTINCT r.return_id)::FLOAT / NULLIF(COUNT(DISTINCT o.order_id), 0) AS return_rate "
                       "FROM orders o JOIN order_items oi ON o.order_id = oi.order_id "
                       "JOIN skus s ON oi.sku_id = s.sku_id "
                       "JOIN categories c ON s.category_id = c.category_id "
                       "LEFT JOIN returns r ON o.order_id = r.order_id "
                       "WHERE o.created_at AT TIME ZONE 'America/Sao_Paulo' >= DATE_TRUNC('quarter', "
                       "CURRENT_DATE AT TIME ZONE 'America/Sao_Paulo' - INTERVAL '3 months') "
                       "AND o.created_at AT TIME ZONE 'America/Sao_Paulo' < DATE_TRUNC('quarter', "
                       "CURRENT_DATE AT TIME ZONE 'America/Sao_Paulo') "
                       "AND o.is_deleted = 0 AND c.is_deleted = 0 "
                       "GROUP BY c.category_name ORDER BY return_rate DESC",
                "output_shape": "N行2列，品类名+退货率",
                "tags": ["aggregation", "join", "group_by", "time_filter", "rate"],
            },
            {
                "task_text": "查询各支付方式的订单数和金额汇总",
                "sql": "SELECT p.payment_type, COUNT(DISTINCT p.order_id) AS order_count, "
                       "SUM(p.amount) AS total_amount "
                       "FROM payments p JOIN orders o ON p.order_id = o.order_id "
                       "WHERE o.is_deleted = 0 AND p.is_deleted = 0 "
                       "GROUP BY p.payment_type ORDER BY total_amount DESC",
                "output_shape": "N行3列，支付方式+订单数+金额",
                "tags": ["aggregation", "join", "group_by"],
            },
            {
                "task_text": "查询各州客户数和平均订单金额",
                "sql": "SELECT u.state, COUNT(DISTINCT u.user_id) AS customer_count, "
                       "AVG(o.amount) AS avg_order_amount "
                       "FROM users u JOIN orders o ON u.user_id = o.user_id "
                       "WHERE u.is_deleted = 0 AND o.is_deleted = 0 "
                       "GROUP BY u.state ORDER BY customer_count DESC",
                "output_shape": "N行3列，州+客户数+平均订单金额",
                "tags": ["aggregation", "join", "group_by"],
            },
        ]

        for seed in seeds:
            self.add(**seed)
