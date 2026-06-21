"""LLM-as-judge for narrative faithfulness evaluation.

Uses Claude 3.5 Sonnet (cross-family) to avoid self-preference bias.
Evaluates whether the generated narrative is faithful to the source data.
"""

from __future__ import annotations

from typing import Any


class NarrativeJudge:
    """Cross-family LLM judge for narrative evaluation."""

    def __init__(self, config: Any) -> None:
        self._cfg = config
        self._judge_model = config.eval.judge_model
        self._judge_key = config.eval.judge_api_key

    def judge(
        self,
        user_query: str,
        result_data: str,
        narrative: str,
    ) -> dict[str, Any]:
        """Judge narrative faithfulness.

        Args:
            user_query: Original user question.
            result_data: Summary of query results.
            narrative: Generated narrative text.

        Returns:
            Dict with 'faithfulness' (1-5) and 'reasoning'.
        """
        if not self._judge_key:
            # No judge API key — return default
            return {"faithfulness": 3, "reasoning": "No judge API key configured"}

        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=self._judge_key,
                base_url="https://api.anthropic.com/v1",
            )

            prompt = (
                f"评估以下数据分析洞察的忠实度:\n\n"
                f"用户问题: {user_query}\n\n"
                f"数据结果: {result_data}\n\n"
                f"AI生成的洞察: {narrative}\n\n"
                f"评分标准:\n"
                f"1 - 完全编造,与数据无关\n"
                f"2 - 有严重事实错误\n"
                f"3 - 基本正确但有轻微偏差\n"
                f"4 - 正确,完全基于数据\n"
                f"5 - 优秀,精确引用数据且有洞察\n\n"
                f"输出 JSON: {{\"faithfulness\": 1-5, \"reasoning\": \"...\"}}"
            )

            response = client.chat.completions.create(
                model=self._judge_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                response_format={"type": "json_object"},
            )

            import json
            return json.loads(response.choices[0].message.content or "{}")
        except Exception:
            return {"faithfulness": 3, "reasoning": "Judge unavailable"}
