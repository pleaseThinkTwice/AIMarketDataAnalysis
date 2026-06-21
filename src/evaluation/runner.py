"""Evaluation runner: batch evaluation with metrics aggregation.

Usage:
    runner = EvalRunner(config, agent)
    report = runner.run("spider_mini", version="v3")
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.core.config import AppConfig
from src.evaluation.eval_set import EvalSetLoader, EvalQuery
from src.evaluation.metrics import execution_accuracy, task_success_rate, avg_attempts


class EvalRunner:
    """Runs batch evaluation over an evaluation set."""

    def __init__(self, config: AppConfig, agent: Any) -> None:
        self._cfg = config
        self._agent = agent
        self._loader = EvalSetLoader(config)

    def run(self, eval_set_name: str = "all") -> dict[str, Any]:
        """Run evaluation over the specified set(s).

        Args:
            eval_set_name: "spider_mini", "business_scenarios", or "all".

        Returns:
            Dict with metrics and per-query results.
        """
        queries: list[EvalQuery] = []

        if eval_set_name in ("spider_mini", "all"):
            queries.extend(self._loader.load_spider_mini())
        if eval_set_name in ("business_scenarios", "all"):
            queries.extend(self._loader.load_business_scenarios())

        if not queries:
            return {"error": "No evaluation queries found. Run with sample data first."}

        results = []
        attempts_list = []
        successes = []

        for i, eq in enumerate(queries):
            t0 = time.monotonic()
            try:
                output = self._agent.run(eq.query)
                elapsed = (time.monotonic() - t0) * 1000

                # Judge success
                success = len(output.failed_tasks) == 0 and output.task_results
                successes.append(success)
                attempts_list.append(output.total_attempts)

                results.append({
                    "index": i,
                    "query": eq.query[:100],
                    "success": success,
                    "n_tasks": len(output.plan.tasks) if output.plan else 0,
                    "attempts": output.total_attempts,
                    "failed_tasks": output.failed_tasks,
                    "cost_usd": output.total_cost_usd,
                    "duration_ms": elapsed,
                })
            except Exception as e:
                results.append({
                    "index": i,
                    "query": eq.query[:100],
                    "success": False,
                    "error": str(e),
                })
                successes.append(False)
                attempts_list.append(0)

        # Aggregate metrics
        tsr = task_success_rate(successes)
        avg_att = avg_attempts(attempts_list)

        report = {
            "eval_set": eval_set_name,
            "n_queries": len(queries),
            "task_success_rate": round(tsr, 4),
            "avg_attempts": round(avg_att, 2),
            "n_successes": sum(successes),
            "n_failures": len(successes) - sum(successes),
            "results": results,
        }

        # Save report
        output_dir = Path(self._cfg.eval.eval_output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        report_path = output_dir / f"eval_{eval_set_name}_{ts}.json"
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, default=str)

        return report
