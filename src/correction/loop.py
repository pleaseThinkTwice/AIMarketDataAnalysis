"""Self-correction loop (standalone, not LangGraph-dependent).

Provides execute_with_correction() which is used by the orchestrator.
The loop runs: generate → execute → (critic) → regenerate (up to max_attempts).
"""

from __future__ import annotations
# Minimal placeholder — the correction loop logic is in orchestrator.py's
# _execute_with_correction method. This module provides helpers.
