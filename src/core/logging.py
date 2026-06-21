"""Structured logging and token cost tracking.

Usage:
    from src.core.logging import get_logger, TokenCostTracker

    logger = get_logger(__name__)
    logger.info("starting_analysis", user_query="...")

    tracker = TokenCostTracker()
    tracker.record(input_tokens=500, output_tokens=200, model="deepseek-chat")
    print(tracker.summary())
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


# ---------------------------------------------------------------------------
# Token pricing (USD per 1M tokens) — update as pricing changes
# ---------------------------------------------------------------------------

# DeepSeek-V3 pricing: $0.27 / 1M input, $1.10 / 1M output (as of 2025)
_PRICE_PER_1M_INPUT = 0.27
_PRICE_PER_1M_OUTPUT = 1.10

# Claude 3.5 Sonnet pricing (for judge): $3.00 / 1M input, $15.00 / 1M output
_CLAUDE_PRICE_PER_1M_INPUT = 3.00
_CLAUDE_PRICE_PER_1M_OUTPUT = 15.00

_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "deepseek-chat": (_PRICE_PER_1M_INPUT, _PRICE_PER_1M_OUTPUT),
    "deepseek-reasoner": (_PRICE_PER_1M_INPUT, _PRICE_PER_1M_OUTPUT),
    "claude-sonnet-4-20250514": (_CLAUDE_PRICE_PER_1M_INPUT, _CLAUDE_PRICE_PER_1M_OUTPUT),
}


# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------


class _StructuredLogger(logging.LoggerAdapter):
    """Logger adapter that adds structured key=value context.

    All keyword arguments to logging calls are treated as structured
    context and formatted into the log message. This avoids passing
    unexpected kwargs to the underlying Logger._log().
    """

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        # Collect all keyword args as structured context
        extra = kwargs.pop("extra", {})
        context = dict(self.extra)
        context.update(extra)

        # Remaining kwargs (e.g., logger.info("msg", key=value)) become context
        context.update(kwargs)

        if context:
            parts = [f"{k}={v!r}" for k, v in context.items()]
            msg = f"{msg} | {' '.join(parts)}"

        # Return empty kwargs — we consumed everything into the message
        return msg, {}


def get_logger(name: str, **context: Any) -> _StructuredLogger:
    """Get a structured logger with optional default context.

    Args:
        name: Logger name (typically __name__).
        **context: Default key=value pairs added to every log message.

    Example:
        logger = get_logger(__name__, component="sql_gen")
        logger.info("generating_sql", task_id=1)
    """
    logger = logging.getLogger(name)
    # Ensure the logger has at least a NullHandler if none configured
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return _StructuredLogger(logger, context)


# ---------------------------------------------------------------------------
# Token cost tracker (thread-safe singleton)
# ---------------------------------------------------------------------------


@dataclass
class _CallRecord:
    """Record of a single LLM API call."""
    timestamp: float
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: float
    label: str = ""  # e.g. "planner", "sql_gen", "critic"


@dataclass
class _TokenTrackerState:
    """Mutable state behind the TokenCostTracker singleton."""
    calls: list[_CallRecord] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)


class TokenCostTracker:
    """Thread-safe singleton tracker for LLM token usage and cost.

    Usage:
        tracker = TokenCostTracker()

        # After each LLM call:
        tracker.record(
            input_tokens=500, output_tokens=200,
            model="deepseek-chat", label="sql_gen", duration_ms=1200,
        )

        # Get summary:
        print(tracker.summary())
        # "3 calls | 4,500 in | 1,800 out | $0.0032"
    """

    _instance: TokenCostTracker | None = None
    _state: _TokenTrackerState = _TokenTrackerState()

    def __new__(cls) -> TokenCostTracker:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "deepseek-chat",
        label: str = "",
        duration_ms: float = 0.0,
    ) -> None:
        """Record a single LLM API call."""
        call = _CallRecord(
            timestamp=time.time(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_ms=duration_ms,
            label=label,
        )
        with self._state.lock:
            self._state.calls.append(call)

    def record_response(self, response: Any, *, label: str = "", model: str = "") -> None:
        """Record from an LLMResponse object.

        Args:
            response: LLMResponse instance with input_tokens, output_tokens, model, duration_ms.
            label: Optional label for this call.
            model: Override model name (uses response.model if empty).
        """
        self.record(
            input_tokens=getattr(response, "input_tokens", 0),
            output_tokens=getattr(response, "output_tokens", 0),
            model=model or getattr(response, "model", "deepseek-chat"),
            label=label,
            duration_ms=getattr(response, "duration_ms", 0.0),
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def total_input_tokens(self) -> int:
        with self._state.lock:
            return sum(c.input_tokens for c in self._state.calls)

    @property
    def total_output_tokens(self) -> int:
        with self._state.lock:
            return sum(c.output_tokens for c in self._state.calls)

    @property
    def total_calls(self) -> int:
        with self._state.lock:
            return len(self._state.calls)

    @property
    def total_duration_ms(self) -> float:
        with self._state.lock:
            return sum(c.duration_ms for c in self._state.calls)

    def total_cost_usd(self) -> float:
        """Calculate total cost across all recorded calls."""
        total = 0.0
        with self._state.lock:
            for call in self._state.calls:
                price_in, price_out = _MODEL_PRICING.get(
                    call.model, (_PRICE_PER_1M_INPUT, _PRICE_PER_1M_OUTPUT),
                )
                total += (call.input_tokens / 1_000_000) * price_in
                total += (call.output_tokens / 1_000_000) * price_out
        return total

    def cost_by_label(self) -> dict[str, float]:
        """Break down cost by label (e.g., planner, sql_gen, critic)."""
        costs: dict[str, float] = {}
        with self._state.lock:
            for call in self._state.calls:
                label = call.label or "unlabeled"
                price_in, price_out = _MODEL_PRICING.get(
                    call.model, (_PRICE_PER_1M_INPUT, _PRICE_PER_1M_OUTPUT),
                )
                cost = (call.input_tokens / 1_000_000) * price_in + \
                       (call.output_tokens / 1_000_000) * price_out
                costs[label] = costs.get(label, 0.0) + cost
        return costs

    def summary(self) -> str:
        """Return a human-readable one-line summary."""
        return (
            f"{self.total_calls} calls | "
            f"{self.total_input_tokens:,} in | "
            f"{self.total_output_tokens:,} out | "
            f"${self.total_cost_usd():.4f} | "
            f"{self.total_duration_ms / 1000:.1f}s"
        )

    def detailed_summary(self) -> str:
        """Return a multi-line summary with per-label breakdown."""
        lines = [
            f"Token Cost Summary",
            f"  Total calls:  {self.total_calls}",
            f"  Input tokens: {self.total_input_tokens:,}",
            f"  Output tokens:{self.total_output_tokens:,}",
            f"  Total cost:   ${self.total_cost_usd():.6f}",
            f"  Total time:   {self.total_duration_ms / 1000:.1f}s",
            f"",
            f"  By label:",
        ]
        for label, cost in sorted(self.cost_by_label().items()):
            lines.append(f"    {label}: ${cost:.6f}")
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset all tracking state."""
        with self._state.lock:
            self._state.calls.clear()
