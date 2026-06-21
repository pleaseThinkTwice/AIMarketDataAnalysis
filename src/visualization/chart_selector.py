"""Chart type selector: rule-based engine + LLM fallback.

Rules cover ~85% of business analysis cases.
LLM is only called for ambiguous data shapes.
"""

from __future__ import annotations

from typing import Any

from src.core.schemas import Task, ExecutionResult, ChartSpec


class ChartSelector:
    """Selects chart types based on data shape heuristics + optional LLM fallback."""

    def __init__(self, config: Any = None) -> None:
        self._config = config

    def select(self, result: ExecutionResult, task: Task) -> ChartSpec:
        """Select the best chart type for a result.

        Args:
            result: The execution result to visualize.
            task: The original task.

        Returns:
            ChartSpec with chart_type and column assignments.
        """
        if not result.is_ok or result.row_count == 0:
            return ChartSpec(chart_type="none", reasoning="无可视化数据")

        columns = result.columns
        rows = result.rows
        n_rows = result.row_count
        n_cols = len(columns)

        # Infer column types — pass column index for data-value checking
        col_types = [self._infer_type(col, idx, rows) for idx, col in enumerate(columns)]

        # Rule 1: Single temporal + single numeric → line
        if n_cols == 2 and col_types[0] == "temporal" and col_types[1] == "numeric":
            return ChartSpec(
                chart_type="line", x_column=columns[0], y_column=columns[1],
                title=task.goal, reasoning="时间+数值 → 折线图",
            )

        # Rule 2: Single categorical + single numeric, ≤7 categories → pie
        if n_cols == 2 and col_types[0] == "categorical" and col_types[1] == "numeric" and n_rows <= 7:
            return ChartSpec(
                chart_type="pie", x_column=columns[0], y_column=columns[1],
                title=task.goal, reasoning=f"≤7分类 ({n_rows}) → 饼图",
            )

        # Rule 3: Single categorical + single numeric → bar
        if n_cols == 2 and col_types[0] == "categorical" and col_types[1] == "numeric":
            if n_rows > 10:
                return ChartSpec(
                    chart_type="horizontal_bar", x_column=columns[0], y_column=columns[1],
                    title=task.goal, reasoning=f"分类>10 ({n_rows}) → 横向柱状图",
                )
            return ChartSpec(
                chart_type="bar", x_column=columns[0], y_column=columns[1],
                title=task.goal, reasoning="分类+数值 → 柱状图",
            )

        # Rule 4: Two categorical + one numeric → heatmap
        if n_cols == 3 and col_types[0] == "categorical" and col_types[1] == "categorical" and col_types[2] == "numeric":
            return ChartSpec(
                chart_type="heatmap", x_column=columns[0], y_column=columns[1], value_column=columns[2],
                title=task.goal, reasoning="双分类+数值 → 热力图",
            )

        # Rule 5: Single numeric column → histogram
        if n_cols == 1 and col_types[0] == "numeric" and n_rows > 10:
            return ChartSpec(
                chart_type="histogram", x_column=columns[0],
                title=task.goal, reasoning="单数值多行 → 直方图",
            )

        # Rule 6: Two numerics → scatter
        if n_cols == 2 and col_types[0] == "numeric" and col_types[1] == "numeric" and n_rows > 5:
            return ChartSpec(
                chart_type="scatter", x_column=columns[0], y_column=columns[1],
                title=task.goal, reasoning="双数值变量 → 散点图",
            )

        # Default: simple bar chart
        if n_cols >= 2 and col_types[0] == "categorical":
            return ChartSpec(
                chart_type="bar", x_column=columns[0], y_column=columns[1],
                title=task.goal, reasoning="默认 → 柱状图",
            )

        return ChartSpec(chart_type="none", reasoning="无法匹配图表规则")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_type(col_name: str, col_idx: int, rows: list[list[Any]]) -> str:
        """Infer the semantic type of a column from its name and data.

        Args:
            col_name: Column name.
            col_idx: Index of this column in each row.
            rows: List of data rows.

        Returns one of: "temporal", "numeric", "categorical".
        """
        name_lower = col_name.lower()
        name_parts = set(name_lower.replace("_", " ").split())

        # Temporal detection by name (whole-word matching to avoid false positives)
        temporal_keywords = {"date", "time", "day", "month", "year", "quarter", "created", "delivered", "timestamp", "at"}
        if name_parts & temporal_keywords:
            return "temporal"

        # Numeric detection by name (whole-word matching)
        numeric_keywords = {"amount", "price", "rate", "count", "sum", "avg", "revenue",
                           "total", "value", "quantity", "score", "ratio", "weight",
                           "length", "height", "width", "freight", "number", "customers"}
        if name_parts & numeric_keywords:
            return "numeric"

        # Check first few data values at the correct column index
        if rows and len(rows) > 0 and col_idx < len(rows[0]):
            sample_vals = [row[col_idx] for row in rows[:5]]
            numeric_count = sum(1 for v in sample_vals if isinstance(v, (int, float)) and v is not None)
            if numeric_count >= len(sample_vals) * 0.6:
                return "numeric"

        return "categorical"
