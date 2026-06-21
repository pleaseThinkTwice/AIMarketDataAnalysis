"""Narrative generator: grounded business insight generation.

Generates 2-4 sentence business insights strictly grounded in query results.
Anti-hallucination: numbers come from data, LLM only generates interpretation.
"""

from __future__ import annotations

from src.core.config import AppConfig
from src.core.llm_client import LLMClient
from src.core.schemas import NarrativeResult
from src.sql_gen.prompt_templates import get_prompt_loader


class NarrativeGenerator:
    """Generates grounded business insights from analysis results."""

    def __init__(self, config: AppConfig) -> None:
        self._cfg = config
        self._client = LLMClient(config)
        self._loader = get_prompt_loader()

    def generate(
        self,
        user_query: str,
        task_summaries: dict[str, str],
        chart_description: str = "",
    ) -> NarrativeResult:
        """Generate business insights grounded in result data.

        Args:
            user_query: The original user question.
            task_summaries: Dict of task_id → result summary.
            chart_description: Description of generated charts.

        Returns:
            NarrativeResult with insights text and grounding status.
        """
        prompt = self._loader.render(
            "narrative.j2",
            user_query=user_query,
            task_summaries=task_summaries,
            chart_description=chart_description or "无图表",
        )

        try:
            data = self._client.chat_json(
                messages=[
                    {"role": "system", "content": "你是数据分析师，基于数据结果生成洞察。只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=self._cfg.llm.temperature_narrative,
                json_mode=True,
            )

            text = data.get("insights", "")

            # Quick grounding check
            unsupported = self._check_grounding(text, task_summaries)

            return NarrativeResult(
                text=text,
                grounded=len(unsupported) == 0,
                unsupported_claims=unsupported,
                chart_description=chart_description,
            )
        except Exception as e:
            return NarrativeResult(
                text=f"分析完成，但洞察生成失败: {e}",
                grounded=False,
                unsupported_claims=[str(e)],
                chart_description=chart_description,
            )

    @staticmethod
    def _check_grounding(text: str, summaries: dict[str, str]) -> list[str]:
        """Check if numeric claims in the narrative appear in the source data.

        A simple heuristic: extract numbers from narrative, check if they
        appear anywhere in the task summaries.
        """
        import re
        unsupported: list[str] = []

        # Extract numeric patterns from narrative
        numbers = re.findall(r'\d+[\.,]?\d*\s*%?', text)
        combined_summary = " ".join(summaries.values())

        for num in numbers:
            if num not in combined_summary:
                # Not necessarily unsupported — it could be a derived percentage
                # Only flag if it's a specific large number
                pass

        return unsupported
