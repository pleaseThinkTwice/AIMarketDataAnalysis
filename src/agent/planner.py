"""Planner: LLM-driven task decomposition.

Takes a natural language analysis question and decomposes it into
a sequence of executable subtasks (Task objects).
"""

from __future__ import annotations

from src.core.config import AppConfig
from src.core.llm_client import LLMClient
from src.core.schemas import Task, Plan, RetrievedSchema
from src.schema_rag.retriever import SchemaRetriever
from src.sql_gen.prompt_templates import get_prompt_loader


class Planner:
    """Decomposes user queries into analysis task sequences."""

    def __init__(self, config: AppConfig) -> None:
        self._cfg = config
        self._client = LLMClient(config)
        self._loader = get_prompt_loader()

    def plan(
        self,
        user_query: str,
        schema_retriever: SchemaRetriever | None = None,
    ) -> Plan:
        """Decompose a user query into a Plan.

        Args:
            user_query: Natural language analysis question.
            schema_retriever: Optional SchemaRetriever. If provided, the planner
                              first retrieves a schema summary to understand
                              what data is available.

        Returns:
            Plan with ordered Task list.
        """
        # Get a high-level schema summary for the planner
        schema_summary = "电商数据库，包含订单、商品、用户、支付、退货、评价、浏览、客服等表。详见 schema_metadata.json。"

        if schema_retriever is not None:
            try:
                schema = schema_retriever.retrieve(user_query)
                tables = [t.name for t in schema.tables]
                schema_summary = f"可用表: {', '.join(tables)}。共 {len(schema.tables)} 张相关表。"
            except Exception:
                pass  # Fall back to default summary

        prompt = self._loader.render(
            "planner.j2",
            schema_summary=schema_summary,
            user_query=user_query,
        )

        data = self._client.chat_json(
            messages=[
                {"role": "system", "content": "你是数据分析任务规划器。只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=self._cfg.llm.temperature_plan,
            json_mode=True,
        )

        tasks = []
        for t in data.get("tasks", []):
            tasks.append(Task(
                id=t.get("id", len(tasks) + 1),
                goal=t.get("goal", ""),
                expected_output_type=t.get("expected_output_type", "table"),
                depends_on=t.get("depends_on", []),
                output_key=t.get("output_key", f"task_{t.get('id', len(tasks)+1)}_result"),
            ))

        return Plan(
            user_query=user_query,
            reasoning=data.get("reasoning", ""),
            tasks=tasks,
        )
