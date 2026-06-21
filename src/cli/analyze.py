"""CLI: Run a single analysis query.

Usage:
    python -m src.cli.analyze "上月销售额最高的三个品类"
    python -m src.cli.analyze "上季度退货率最高的品类" --debug --save-charts
"""

from __future__ import annotations


def main() -> None:
    """Run analysis on a natural language query."""
    import argparse

    parser = argparse.ArgumentParser(description="Run data analysis query")
    parser.add_argument("query", type=str, help="Natural language analysis question")
    parser.add_argument("--debug", action="store_true", help="Show intermediate SQLs")
    parser.add_argument("--save-charts", action="store_true", help="Save chart outputs")
    parser.add_argument("--config", type=str, default=None, help="Config path")
    args = parser.parse_args()

    from src.core.config import load_config
    from src.core.logging import TokenCostTracker
    from src.agent.orchestrator import AnalysisAgent

    config = load_config(args.config)
    tracker = TokenCostTracker()
    tracker.reset()

    print(f"\n{'='*60}")
    print(f"Query: {args.query}")
    print(f"{'='*60}\n")

    agent = AnalysisAgent(config)
    output = agent.run(args.query)

    # Print results
    if output.plan:
        print(f"Plan ({len(output.plan.tasks)} tasks):")
        for task in output.plan.tasks:
            print(f"  [{task.id}] {task.goal}")
        print()

    if args.debug:
        print("Generated SQLs:")
        for sa in output.sql_log:
            print(f"  --- Attempt {sa.attempt_number} ---")
            print(f"  Reasoning: {sa.reasoning[:200]}")
            print(f"  SQL: {sa.sql[:300]}")
            print()

    print("Results:")
    for tid, result in output.task_results.items():
        if result.is_ok:
            print(f"  Task {tid}: {result.row_count} rows x {len(result.columns)} cols")
            print(f"    Columns: {', '.join(result.columns[:5])}")
            if result.rows:
                for row in result.rows[:3]:
                    print(f"    {row}")
        else:
            print(f"  Task {tid}: FAILED — {result.error[:100] if result.error else 'Unknown'}")

    if output.charts:
        print(f"\nCharts: {len(output.charts)} generated")
        for c in output.charts:
            print(f"  {c}")

    if output.narrative and output.narrative.text:
        print(f"\nInsights:\n  {output.narrative.text}")

    print(f"\n{'='*60}")
    print(f"Cost: ${output.total_cost_usd:.6f} | Time: {output.duration_ms/1000:.1f}s | Attempts: {output.total_attempts}")
    if output.failed_tasks:
        print(f"Failed tasks: {output.failed_tasks}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
