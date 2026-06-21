"""SQL Generator: LLM-powered SQL generation with schema context.

Handles both initial generation and error-driven regeneration.

Usage:
    gen = SQLGenerator(config)
    result = gen.generate(task, schema, few_shots, upstream)
    # result: SQLAttempt with sql, reasoning, expected_output_shape
"""

from __future__ import annotations

import json

from src.core.config import AppConfig
from src.core.llm_client import LLMClient
from src.core.logging import TokenCostTracker
from src.core.schemas import Task, RetrievedSchema, FewShotExample, SQLAttempt
from src.sql_gen.prompt_templates import get_prompt_loader


class SQLGenerator:
    """Generates PostgreSQL SQL from task descriptions + schema context."""

    def __init__(self, config: AppConfig) -> None:
        self._cfg = config
        self._client = LLMClient(config)
        self._loader = get_prompt_loader()
        self._tracker = TokenCostTracker()

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(
        self,
        task: Task,
        schema: RetrievedSchema,
        few_shots: list[FewShotExample] | None = None,
        upstream: dict[int, str] | None = None,
    ) -> SQLAttempt:
        """Generate SQL for a single task.

        Args:
            task: The task to generate SQL for.
            schema: Retrieved schema context.
            few_shots: Top-k similar exemplars (from FewShotRetriever).
            upstream: Dict of task_id → result summary for dependencies.

        Returns:
            SQLAttempt with reasoning, sql, expected_output_shape.
        """
        prompt = self._loader.render(
            "sql_gen.j2",
            schema=schema,
            task=task,
            few_shot_examples=few_shots or [],
            upstream=upstream or {},
        )

        data = self._client.chat_json(
            messages=[
                {"role": "system", "content": "你是一个专业的 PostgreSQL SQL 生成助手。只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=self._cfg.llm.temperature_sql,
            json_mode=True,
        )

        return SQLAttempt(
            attempt_number=1,
            sql=data.get("sql", ""),
            reasoning=data.get("reasoning", ""),
            expected_output_shape=data.get("expected_output_shape", ""),
        )

    def regenerate(
        self,
        task: Task,
        previous_attempt: SQLAttempt,
        error_message: str,
        error_class: str,
        schema: RetrievedSchema,
    ) -> SQLAttempt:
        """Regenerate SQL after an execution error.

        Args:
            task: The original task.
            previous_attempt: The failed SQL attempt.
            error_message: The database error message.
            error_class: One of "syntax", "schema", "type", "semantic".
            schema: Re-retrieved schema context.

        Returns:
            New SQLAttempt with corrected SQL.
        """
        error_descriptions = {
            "syntax": "SQL 语法错误 — 可能是拼写、括号、逗号等问题。",
            "schema": "Schema 错误 — 表名或字段名不存在或拼写错误。请仔细检查 schema 中的表名和字段名。",
            "type": "类型错误 — 对非数字字段做了算术运算，或 JOIN 两侧类型不匹配。",
            "semantic": "语义错误 — SQL 语法正确但结果不符合预期，可能是 WHERE 条件覆盖了错误范围、漏了 GROUP BY 或 JOIN 条件。",
        }

        prompt = self._loader.render(
            "sql_regenerate.j2",
            task=task,
            previous_sql=previous_attempt.sql,
            previous_reasoning=previous_attempt.reasoning,
            error_message=error_message,
            error_class=error_class,
            error_class_description=error_descriptions.get(error_class, "未知错误"),
            schema=schema,
        )

        data = self._client.chat_json(
            messages=[
                {"role": "system", "content": "你是 SQL 修复专家。基于错误信息修正 SQL。只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=self._cfg.llm.temperature_sql,
            json_mode=True,
        )

        return SQLAttempt(
            attempt_number=previous_attempt.attempt_number + 1,
            sql=data.get("sql", ""),
            reasoning=data.get("reasoning", ""),
            expected_output_shape=data.get("expected_output_shape", ""),
        )
