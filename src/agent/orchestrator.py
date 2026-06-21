"""Agent orchestrator: the top-level entry point for analysis.

Wires together all components and executes the Plan-and-Execute loop.
Handles task iteration manually (sequential, not DAG-parallel) since
LangGraph's state machine already encodes the per-task correction loop.

Usage:
    from src.core.config import load_config
    from src.agent.orchestrator import AnalysisAgent

    cfg = load_config()
    agent = AnalysisAgent(cfg)
    output = agent.run("上月销售额最高的三个品类是什么")
    print(output.narrative.text if output.narrative else "No narrative")
"""

from __future__ import annotations

import time
from typing import Any

from src.core.config import AppConfig
from src.core.schemas import (
    Task, Plan, ExecutionResult, SQLAttempt, AnalysisOutput,
    AgentStatus, ExecutionStatus, ErrorClass,
)
from src.core.logging import get_logger, TokenCostTracker

logger = get_logger(__name__, component="orchestrator")


class AnalysisAgent:
    """Top-level analysis agent: receives NL queries, returns AnalysisOutput."""

    def __init__(self, config: AppConfig) -> None:
        self._cfg = config
        self._tracker = TokenCostTracker()

        # Lazy-initialized components
        self._planner = None
        self._retriever = None
        self._generator = None
        self._few_shot_retriever = None
        self._security = None
        self._critic = None
        self._chart_selector = None
        self._renderer = None
        self._narrative_gen = None

    # ------------------------------------------------------------------
    # Lazy init helpers
    # ------------------------------------------------------------------

    @property
    def planner(self):
        if self._planner is None:
            from src.agent.planner import Planner
            self._planner = Planner(self._cfg)
        return self._planner

    @property
    def retriever(self):
        if self._retriever is None:
            from src.schema_rag.retriever import SchemaRetriever
            self._retriever = SchemaRetriever(self._cfg)
            self._retriever.initialize()
        return self._retriever

    @property
    def generator(self):
        if self._generator is None:
            from src.sql_gen.generator import SQLGenerator
            self._generator = SQLGenerator(self._cfg)
        return self._generator

    @property
    def few_shot_retriever(self):
        if self._few_shot_retriever is None:
            from src.sql_gen.few_shot_retriever import FewShotRetriever
            self._few_shot_retriever = FewShotRetriever()
        return self._few_shot_retriever

    @property
    def security(self):
        if self._security is None:
            from src.executor.security import SecurityPipeline
            self._security = SecurityPipeline(self._cfg)
        return self._security

    @property
    def critic(self):
        if self._critic is None:
            from src.correction.critic import Critic
            self._critic = Critic(self._cfg)
        return self._critic

    @property
    def chart_selector(self):
        if self._chart_selector is None:
            from src.visualization.chart_selector import ChartSelector
            self._chart_selector = ChartSelector(self._cfg)
        return self._chart_selector

    @property
    def renderer(self):
        if self._renderer is None:
            from src.visualization.renderer import ChartRenderer
            self._renderer = ChartRenderer(self._cfg)
        return self._renderer

    @property
    def narrative_gen(self):
        if self._narrative_gen is None:
            from src.narrative.generator import NarrativeGenerator
            self._narrative_gen = NarrativeGenerator(self._cfg)
        return self._narrative_gen

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, user_query: str) -> AnalysisOutput:
        """Execute a full analysis from a natural language query.

        Args:
            user_query: Natural language analysis question.

        Returns:
            AnalysisOutput with plan, results, charts, and narrative.
        """
        t0 = time.monotonic()
        logger.info("analysis_start", query=user_query[:100])

        # Step 1: Plan
        plan = self.planner.plan(user_query)
        if not plan.tasks:
            return AnalysisOutput(
                user_query=user_query,
                status="failed",
                error_message="Planner produced no tasks.",
            )

        logger.info("plan_complete", n_tasks=len(plan.tasks), reasoning=plan.reasoning[:100])

        # Step 2: Execute each task sequentially
        task_results: dict[int, ExecutionResult] = {}
        sql_log: list[SQLAttempt] = []
        failed_tasks: list[int] = []
        total_attempts = 0

        for idx, task in enumerate(plan.tasks):
            logger.info("task_executing", idx=idx, task_id=task.id, goal=task.goal[:80])

            # Retrieve schema
            schema = self.retriever.retrieve(task.goal)

            # Get upstream results
            upstream = {}
            for dep_id in task.depends_on:
                if dep_id in task_results:
                    upstream[dep_id] = task_results[dep_id].summary()

            # Get few-shot exemplars
            few_shots = self.few_shot_retriever.retrieve(task.goal)

            # Execute with correction loop
            result, attempts_list, success = self._execute_with_correction(
                task, schema, few_shots, upstream,
            )

            task_results[task.id] = result
            sql_log.extend(attempts_list)
            total_attempts += len(attempts_list)

            if not success:
                failed_tasks.append(task.id)
                logger.warning("task_failed", task_id=task.id)

        # Step 3: Generate charts
        charts = []
        chart_specs = []
        for task in plan.tasks:
            if task.id in task_results and task_results[task.id].is_ok:
                result = task_results[task.id]
                spec = self.chart_selector.select(result, task)
                if spec and spec.chart_type != "none":
                    chart_specs.append(spec)
                    path = self.renderer.render(spec, result)
                    if path:
                        charts.append(path)

        # Step 4: Generate narrative
        narrative = None
        try:
            task_summaries = {
                str(tid): r.summary()
                for tid, r in task_results.items()
            }
            chart_desc = ", ".join(s.chart_type for s in chart_specs) if chart_specs else "无图表"
            narrative = self.narrative_gen.generate(
                user_query, task_summaries, chart_desc,
            )
        except Exception as e:
            logger.error("narrative_failed", error=str(e))

        elapsed = (time.monotonic() - t0) * 1000

        output = AnalysisOutput(
            user_query=user_query,
            plan=plan,
            task_results=task_results,
            charts=charts,
            chart_specs=chart_specs if chart_specs else None,
            narrative=narrative,
            sql_log=sql_log,
            total_attempts=total_attempts,
            failed_tasks=failed_tasks,
            total_tokens=self._tracker.total_input_tokens + self._tracker.total_output_tokens,
            total_cost_usd=self._tracker.total_cost_usd(),
            duration_ms=elapsed,
        )

        logger.info(
            "analysis_complete",
            tasks=len(plan.tasks),
            failed=len(failed_tasks),
            attempts=total_attempts,
            cost=f"{output.total_cost_usd:.4f}",
            time=f"{elapsed/1000:.1f}s",
        )

        return output

    # ------------------------------------------------------------------
    # Self-correction loop
    # ------------------------------------------------------------------

    def _execute_with_correction(
        self,
        task: Task,
        schema: Any,
        few_shots: list,
        upstream: dict[int, str],
    ) -> tuple[ExecutionResult, list[SQLAttempt], bool]:
        """Execute a task with up to max_attempts correction attempts.

        Returns:
            (final_result, all_attempts, success_flag)
        """
        max_attempts = self._cfg.correction.max_attempts
        attempts: list[SQLAttempt] = []

        # Initial generation
        attempt = self.generator.generate(task, schema, few_shots, upstream)
        attempts.append(attempt)

        for try_num in range(max_attempts):
            # Execute
            result = self.security.validate_and_execute(attempt.sql)
            result.task_id = task.id
            result.sql = attempt.sql

            if result.is_ok:
                # Critic check (if enabled)
                if self._cfg.correction.enable_critic:
                    try:
                        verdict = self.critic.check(
                            task, attempt.sql, result, attempt.expected_output_shape,
                        )
                        if verdict.acceptable:
                            return (result, attempts, True)
                        else:
                            # Semantic error — treat as failure for regeneration
                            result = ExecutionResult.error_result(
                                task.id, attempt.sql,
                                verdict.feedback, ErrorClass.SEMANTIC,
                            )
                    except Exception:
                        # Critic failed — accept the result anyway
                        return (result, attempts, True)
                else:
                    return (result, attempts, True)

            # Regenerate if we have more attempts
            if try_num < max_attempts - 1:
                # Re-retrieve schema with error info
                enriched_query = f"{task.goal} {result.error or ''}"
                try:
                    schema = self.retriever.retrieve(enriched_query)
                except Exception:
                    pass

                error_class = result.error_class.value if result.error_class else "unknown"
                attempt = self.generator.regenerate(
                    task, attempt, result.error or "Unknown error", error_class, schema,
                )
                attempts.append(attempt)

        # All attempts exhausted
        return (result, attempts, False)
