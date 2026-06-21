"""Critic: LLM-based result sanity checker.

Checks execution results for semantic errors that the DB can't catch
(SQL runs fine but produces wrong results).
"""

from __future__ import annotations

from src.core.config import AppConfig
from src.core.llm_client import LLMClient
from src.core.schemas import Task, ExecutionResult, CriticVerdict
from src.sql_gen.prompt_templates import get_prompt_loader


class Critic:
    """Reviews execution results for semantic correctness."""

    def __init__(self, config: AppConfig) -> None:
        self._cfg = config
        self._client = LLMClient(config)
        self._loader = get_prompt_loader()

    def check(
        self,
        task: Task,
        sql: str,
        result: ExecutionResult,
        expected_shape: str = "",
    ) -> CriticVerdict:
        """Check if an execution result is semantically acceptable.

        Args:
            task: The task that was executed.
            sql: The SQL that was executed.
            result: The execution result to evaluate.
            expected_shape: Expected output shape from the generation step.

        Returns:
            CriticVerdict with acceptability judgment.
        """
        # Quick deterministic checks first
        issues: list[str] = []

        # Check 1: Empty result when data is expected
        if result.row_count == 0 and "count" not in task.goal.lower():
            issues.append("结果为空，可能 WHERE 条件过滤掉所有数据")

        # Check 2: Calculate null ratio
        null_ratio = 0.0
        if result.rows and result.row_count > 0:
            null_count = sum(
                1 for row in result.rows for val in row if val is None
            )
            total_cells = result.row_count * len(result.columns)
            null_ratio = null_count / total_cells if total_cells > 0 else 0.0

        if null_ratio > self._cfg.correction.critic.max_null_ratio:
            issues.append(f"空值率 {null_ratio:.1%} 超过阈值 {self._cfg.correction.critic.max_null_ratio:.0%}，可能 JOIN 类型错误")

        # If deterministic checks found issues, we can return early
        # Otherwise, use LLM for deeper review
        if not issues:
            # Quick accept for reasonable results
            return CriticVerdict(
                acceptable=True,
                feedback="通过确定性检查（行数>0、空值率正常）",
                confidence=0.9,
                null_ratio=null_ratio,
                issues=[],
            )

        # Use LLM for borderline cases
        try:
            prompt = self._loader.render(
                "critic.j2",
                task=task,
                sql=sql,
                expected_shape=expected_shape,
                row_count=result.row_count,
                col_count=len(result.columns),
                columns=", ".join(result.columns[:10]),
                null_ratio=f"{null_ratio:.1%}",
                sample_rows=str(result.rows[:5]) if result.rows else "无数据",
            )

            data = self._client.chat_json(
                messages=[
                    {"role": "system", "content": "你是数据分析结果审查员。只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=self._cfg.llm.temperature_critic,
                json_mode=True,
            )

            return CriticVerdict(
                acceptable=data.get("acceptable", True),
                feedback=data.get("feedback", ""),
                confidence=data.get("confidence", 0.8),
                null_ratio=null_ratio,
                issues=data.get("issues", issues),
            )
        except Exception:
            # LLM unavailable — use deterministic verdict
            return CriticVerdict(
                acceptable=len(issues) <= 1,
                feedback="; ".join(issues) if issues else "无法执行 LLM 审查，使用启发式检查",
                confidence=0.6,
                null_ratio=null_ratio,
                issues=issues,
            )
