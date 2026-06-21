"""Evaluation dataset loader.

Loads two evaluation sets:
    1. Spider-mini (200 queries) — single-step NL2SQL accuracy
    2. Business scenarios (80 queries) — end-to-end agent task success
"""

from __future__ import annotations

import json
from pathlib import Path

from src.core.schemas import Task


class EvalQuery:
    """A single evaluation query item."""
    def __init__(self, data: dict) -> None:
        self.query: str = data.get("query", "")
        self.expected_tables: list[str] = data.get("expected_tables", [])
        self.gold_sql: str = data.get("gold_sql", "")
        self.gold_result_hash: str = data.get("gold_result_hash", "")
        self.tags: list[str] = data.get("tags", [])
        self.is_multi_step: bool = "multi_step" in self.tags
        self.has_trap: bool = "trap" in self.tags


class EvalSetLoader:
    """Loads and manages evaluation datasets."""

    def __init__(self, config) -> None:
        self._cfg = config
        self._spider_path = Path(config.eval.spider_mini_path)
        self._business_path = Path(config.eval.business_scenarios_path)

    def load_spider_mini(self) -> list[EvalQuery]:
        """Load the Spider-mini evaluation set."""
        return self._load_jsonl(self._spider_path)

    def load_business_scenarios(self) -> list[EvalQuery]:
        """Load the business scenario evaluation set."""
        return self._load_jsonl(self._business_path)

    def load_all(self) -> dict[str, list[EvalQuery]]:
        """Load all evaluation sets."""
        result = {}
        if self._spider_path.exists():
            result["spider_mini"] = self.load_spider_mini()
        if self._business_path.exists():
            result["business_scenarios"] = self.load_business_scenarios()
        return result

    @staticmethod
    def _load_jsonl(path: Path) -> list[EvalQuery]:
        """Load a JSONL evaluation file."""
        if not path.exists():
            return []
        queries = []
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    queries.append(EvalQuery(json.loads(line)))
                except json.JSONDecodeError:
                    continue
        return queries

    @staticmethod
    def create_empty_eval_files(config) -> None:
        """Create empty evaluation JSONL files with example entries."""
        spider_path = Path(config.eval.spider_mini_path)
        business_path = Path(config.eval.business_scenarios_path)
        spider_path.parent.mkdir(parents=True, exist_ok=True)

        if not spider_path.exists():
            with open(spider_path, "w", encoding="utf-8") as fh:
                fh.write('{"query":"统计各品类的订单数量","expected_tables":["orders","order_items","skus","categories"],"gold_sql":"","tags":["single_step","aggregation"]}\n')
                fh.write('{"query":"上个月销售额最高的五个商品","expected_tables":["orders","order_items","skus"],"gold_sql":"","tags":["single_step","top_k","time_filter"]}\n')

        if not business_path.exists():
            with open(business_path, "w", encoding="utf-8") as fh:
                fh.write('{"query":"上季度退货率最高的三个品类是什么,各品类的主要退货原因分布如何","expected_tables":["orders","returns","return_reasons","categories","skus","order_items"],"gold_sql":"","tags":["multi_step","trap","timezone"]}\n')
