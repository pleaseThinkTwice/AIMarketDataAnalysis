"""LangGraph state definition for the Analysis Agent.

Defines AnalysisState (TypedDict) that flows through the graph nodes.
Each node returns a partial dict that gets merged into the full state.
"""

from __future__ import annotations

from typing import TypedDict

from src.core.schemas import (
    Task,
    ExecutionResult,
    RetrievedSchema,
    SQLAttempt,
    CriticVerdict,
    NarrativeResult,
    ChartSpec,
)


class AnalysisState(TypedDict, total=False):
    """State that flows through the Plan-and-Execute graph.

    All keys are optional (total=False) because LangGraph nodes
    return partial updates that get merged.
    """

    # Input
    user_query: str

    # Planning
    plan: list[dict]  # Serialized Task objects
    plan_reasoning: str

    # Execution cursor
    current_task_index: int
    current_task: dict | None

    # Per-task contexts
    schema_contexts: dict[int, dict]  # task_id → serialized RetrievedSchema
    task_results: dict[int, dict]  # task_id → serialized ExecutionResult
    sql_attempts: dict[int, list[dict]]  # task_id → list of SQLAttempt
    correction_attempts: dict[int, int]  # task_id → attempt count
    critic_verdicts: dict[int, dict]  # task_id → CriticVerdict

    # Current SQL being processed
    current_sql: str
    current_reasoning: str
    current_expected_shape: str

    # Outputs
    charts: list[dict]  # ChartSpec
    chart_paths: list[str]  # File paths
    narrative: dict | None  # NarrativeResult
    sql_log: list[dict]  # All SQLAttempt across all tasks

    # Status
    status: str  # "planning" | "executing" | "correcting" | "complete" | "failed"
    failed_tasks: list[int]
    error_message: str
