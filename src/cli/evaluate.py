"""CLI: Run evaluation suite.

Usage:
    python -m src.cli.evaluate --eval-set spider_mini
    python -m src.cli.evaluate --eval-set all --output report.json
"""

from __future__ import annotations


def main() -> None:
    """Run the evaluation suite."""
    import argparse

    parser = argparse.ArgumentParser(description="Run evaluation suite")
    parser.add_argument("--eval-set", type=str, default="spider_mini",
                       choices=["spider_mini", "business_scenarios", "all"],
                       help="Evaluation set to run")
    parser.add_argument("--output", type=str, default=None, help="Output report path")
    parser.add_argument("--config", type=str, default=None, help="Config path")
    args = parser.parse_args()

    from src.core.config import load_config
    from src.evaluation.eval_set import EvalSetLoader
    from src.evaluation.runner import EvalRunner
    from src.agent.orchestrator import AnalysisAgent

    config = load_config(args.config)

    # Ensure eval files exist
    EvalSetLoader.create_empty_eval_files(config)

    agent = AnalysisAgent(config)
    runner = EvalRunner(config, agent)

    print(f"Running evaluation on: {args.eval_set}")
    report = runner.run(args.eval_set)

    if "error" in report:
        print(f"Error: {report['error']}")
        return

    print(f"\nEvaluation Report")
    print(f"{'='*50}")
    print(f"  Queries:        {report['n_queries']}")
    print(f"  Success Rate:   {report['task_success_rate']:.2%}")
    print(f"  Avg Attempts:   {report['avg_attempts']}")
    print(f"  Successes:      {report['n_successes']}")
    print(f"  Failures:       {report['n_failures']}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
