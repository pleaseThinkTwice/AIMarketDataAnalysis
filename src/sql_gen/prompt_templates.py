"""Jinja2 template loader for all LLM prompts.

Prompts are version-controlled in the prompts/ directory as .j2 files.
This loader finds and renders them with the correct context.

Usage:
    loader = PromptLoader()
    rendered = loader.render("sql_gen.j2", schema=..., task=..., ...)
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader


class PromptLoader:
    """Loads and renders Jinja2 prompt templates from prompts/."""

    def __init__(self, prompts_dir: str | Path | None = None) -> None:
        if prompts_dir is None:
            prompts_dir = Path(__file__).resolve().parent.parent.parent / "prompts"
        self._env = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            autoescape=False,  # We're generating prompts, not HTML
        )

    def render(self, template_name: str, **kwargs) -> str:
        """Render a template with the given context.

        Args:
            template_name: e.g. "sql_gen.j2", "planner.j2", etc.
            **kwargs: Template variables.

        Returns:
            Rendered prompt string.
        """
        template = self._env.get_template(template_name)
        return template.render(**kwargs).strip()


# Singleton
_loader: PromptLoader | None = None


def get_prompt_loader() -> PromptLoader:
    global _loader
    if _loader is None:
        _loader = PromptLoader()
    return _loader
