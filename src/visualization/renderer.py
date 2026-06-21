"""Chart renderer: matplotlib (PNG) + plotly (HTML).

Handles CJK font registration and renders charts to output files.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.core.schemas import ExecutionResult, ChartSpec


class ChartRenderer:
    """Renders chart specifications to image/HTML files."""

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._output_dir = Path("outputs")
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._font_configured = False

    def render(
        self,
        spec: ChartSpec,
        result: ExecutionResult,
        output_name: str | None = None,
    ) -> str | None:
        """Render a chart and return the output file path.

        Args:
            spec: Chart specification.
            result: Execution result to visualize.
            output_name: Optional output filename (without extension).

        Returns:
            Path to the rendered file, or None if rendering failed.
        """
        if spec.chart_type == "none":
            return None

        self._ensure_font()

        if output_name is None:
            import hashlib
            h = hashlib.md5(str(spec.model_dump()).encode()).hexdigest()[:8]
            output_name = f"chart_{spec.chart_type}_{h}"

        fmt = self._config.viz.default_format if self._config else "png"

        try:
            if fmt == "html":
                return self._render_plotly(spec, result, output_name)
            else:
                return self._render_matplotlib(spec, result, output_name)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Chart render failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Matplotlib rendering
    # ------------------------------------------------------------------

    def _render_matplotlib(self, spec: ChartSpec, result: ExecutionResult, name: str) -> str:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        dpi = self._config.viz.dpi if self._config else 150
        path = str(self._output_dir / f"{name}.png")

        cols = result.columns
        rows = result.rows

        fig, ax = plt.subplots(figsize=(10, 6), dpi=dpi)

        if spec.chart_type == "bar":
            x = [r[cols.index(spec.x_column)] if spec.x_column in cols else str(r[0])
                 for r in rows]
            y = [float(r[cols.index(spec.y_column)]) if spec.y_column in cols else float(r[1])
                 for r in rows]
            ax.bar(range(len(x)), y, color="steelblue")
            ax.set_xticks(range(len(x)))
            ax.set_xticklabels([str(v)[:20] for v in x], rotation=45, ha="right", fontsize=8)

        elif spec.chart_type == "horizontal_bar":
            x = [r[cols.index(spec.x_column)] if spec.x_column in cols else str(r[0])
                 for r in rows]
            y = [float(r[cols.index(spec.y_column)]) if spec.y_column in cols else float(r[1])
                 for r in rows]
            ax.barh(range(len(x)), y, color="steelblue")
            ax.set_yticks(range(len(x)))
            ax.set_yticklabels([str(v)[:30] for v in x], fontsize=8)

        elif spec.chart_type == "line":
            x = [r[cols.index(spec.x_column)] if spec.x_column in cols else str(r[0])
                 for r in rows]
            y = [float(r[cols.index(spec.y_column)]) if spec.y_column in cols else float(r[1])
                 for r in rows]
            ax.plot(x, y, marker="o", color="steelblue")

        elif spec.chart_type == "histogram":
            vals = [float(r[cols.index(spec.x_column)]) if spec.x_column in cols else float(r[0])
                    for r in rows]
            ax.hist(vals, bins=min(20, len(vals)), color="steelblue", edgecolor="white")

        elif spec.chart_type == "scatter":
            x = [float(r[cols.index(spec.x_column)]) if spec.x_column in cols else float(r[0])
                 for r in rows]
            y = [float(r[cols.index(spec.y_column)]) if spec.y_column in cols else float(r[1])
                 for r in rows]
            ax.scatter(x, y, alpha=0.6, color="steelblue")

        elif spec.chart_type == "pie":
            labels = [r[cols.index(spec.x_column)] if spec.x_column in cols else str(r[0])
                      for r in rows]
            vals = [float(r[cols.index(spec.y_column)]) if spec.y_column in cols else float(r[1])
                    for r in rows]
            ax.pie(vals, labels=[str(l)[:15] for l in labels], autopct="%1.1f%%")

        else:
            plt.close()
            return None

        ax.set_title(spec.title, fontsize=12)
        fig.tight_layout()
        fig.savefig(path, dpi=dpi, bbox_inches="tight")
        plt.close(fig)

        return path

    # ------------------------------------------------------------------
    # Plotly rendering
    # ------------------------------------------------------------------

    def _render_plotly(self, spec: ChartSpec, result: ExecutionResult, name: str) -> str:
        try:
            import plotly.graph_objects as go
        except ImportError:
            return self._render_matplotlib(spec, result, name)

        path = str(self._output_dir / f"{name}.html")

        # Simplified — just use bar for everything in plotly
        cols = result.columns
        rows = result.rows
        x = [r[0] for r in rows]
        y = [float(r[1]) if len(r) > 1 else 0 for r in rows]

        fig = go.Figure(data=[go.Bar(x=x, y=y)])
        fig.update_layout(title=spec.title)
        fig.write_html(path)

        return path

    # ------------------------------------------------------------------
    # Font configuration
    # ------------------------------------------------------------------

    def _ensure_font(self) -> None:
        """Ensure CJK fonts are available for matplotlib."""
        if self._font_configured:
            return

        font_family = self._config.viz.font_family if self._config else "Noto Sans CJK SC"

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.font_manager as fm

            # Try to find the font
            available = {f.name for f in fm.fontManager.ttflist}
            if font_family not in available:
                # Fall back to sans-serif
                font_family = "sans-serif"

            import matplotlib.pyplot as plt
            plt.rcParams["font.family"] = font_family
            plt.rcParams["axes.unicode_minus"] = False
        except Exception:
            pass

        self._font_configured = True
