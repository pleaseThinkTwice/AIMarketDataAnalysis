"""CJK font configuration for matplotlib.

Registers Noto Sans CJK SC (or fallback) to prevent tofu/boxes in Chinese text.
"""

from __future__ import annotations


def configure_cjk_fonts(font_family: str = "Noto Sans CJK SC") -> None:
    """Configure matplotlib for Chinese/Japanese/Korean text rendering.

    Call once at application startup.

    Args:
        font_family: Preferred CJK font family name.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.font_manager as fm
        import matplotlib.pyplot as plt

        available = {f.name for f in fm.fontManager.ttflist}

        # Try preferred font, then common CJK fonts
        candidates = [font_family, "Noto Sans CJK SC", "WenQuanYi Micro Hei",
                      "SimHei", "Microsoft YaHei", "Arial Unicode MS"]
        chosen = None
        for candidate in candidates:
            if candidate in available:
                chosen = candidate
                break

        if chosen:
            plt.rcParams["font.family"] = chosen
        plt.rcParams["axes.unicode_minus"] = False

    except Exception:
        pass  # Headless environment — no matplotlib needed yet
