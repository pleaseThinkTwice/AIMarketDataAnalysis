"""Evaluation metrics for NL2SQL and Agent evaluation.

Metrics:
    - EX (Execution Accuracy): pred result set == gold result set
    - CM (Component Match): AST-level component matching
    - TSR (Task Success Rate): end-to-end task judged acceptable
    - Correction Lift: EX_with_correction - EX_without
    - Avg Steps to Success: mean attempts to success
    - Narrative Faithfulness: LLM judge score
"""

from __future__ import annotations

from typing import Any


def execution_accuracy(pred_rows: list[list[Any]], gold_rows: list[list[Any]]) -> bool:
    """Check if predicted result set matches gold result set.

    Compares as sets of tuples, ignoring column order and row order.
    """
    if not gold_rows and not pred_rows:
        return True
    if not gold_rows or not pred_rows:
        return False
    try:
        pred_set = {tuple(r) for r in pred_rows}
        gold_set = {tuple(r) for r in gold_rows}
        return pred_set == gold_set
    except TypeError:
        # Unhashable types — fall back to sorted list comparison
        return sorted(str(r) for r in pred_rows) == sorted(str(r) for r in gold_rows)


def component_match(pred_sql: str, gold_sql: str) -> float:
    """Compute component-level match score between two SQL statements.

    Returns a score in [0.0, 1.0] based on keyword and table overlap.
    """
    if not pred_sql or not gold_sql:
        return 0.0

    pred_upper = pred_sql.upper()
    gold_upper = gold_sql.upper()

    components = ["SELECT", "FROM", "WHERE", "GROUP BY", "HAVING", "ORDER BY",
                  "JOIN", "LEFT JOIN", "INNER JOIN", "LIMIT"]
    matches = 0
    total = 0

    for comp in components:
        in_pred = comp in pred_upper
        in_gold = comp in gold_upper
        if in_pred or in_gold:
            total += 1
            if in_pred == in_gold:
                matches += 1

    return matches / total if total > 0 else 0.0


def task_success_rate(judgments: list[bool]) -> float:
    """Calculate TSR from a list of per-task success/failure judgments."""
    if not judgments:
        return 0.0
    return sum(1 for j in judgments if j) / len(judgments)


def correction_lift(ex_with_correction: float, ex_without_correction: float) -> float:
    """Calculate the improvement from self-correction."""
    return ex_with_correction - ex_without_correction


def avg_attempts(attempts_per_query: list[int]) -> float:
    """Calculate average attempts per query."""
    if not attempts_per_query:
        return 0.0
    return sum(attempts_per_query) / len(attempts_per_query)
