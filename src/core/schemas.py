"""Pydantic v2 models for the Data Analysis Agent.

All data that flows through the Agent pipeline is represented as Pydantic models.
This gives us validation, serialization, and a single source of truth for
the shape of data at each stage.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OutputType(str, Enum):
    TABLE = "table"
    SCALAR = "scalar"
    VISUALIZATION = "visualization"


class ExecutionStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


class AgentStatus(str, Enum):
    PLANNING = "planning"
    EXECUTING = "executing"
    CORRECTING = "correcting"
    COMPLETE = "complete"
    FAILED = "failed"


class ErrorClass(str, Enum):
    SYNTAX = "syntax"        # SQL parse/syntax error
    SCHEMA = "schema"        # table or column doesn't exist
    TYPE = "type"            # type mismatch (e.g. VARCHAR + INT)
    SEMANTIC = "semantic"    # SQL runs but result is wrong
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


class Task(BaseModel):
    """A single sub-task in the analysis plan."""
    id: int
    goal: str = Field(..., description="Natural language description of this task")
    expected_output_type: OutputType = OutputType.TABLE
    depends_on: list[int] = Field(default_factory=list, description="Task IDs this depends on")
    output_key: str = Field(default="", description="Key for referencing this task's result")

    def model_post_init(self, __context: Any) -> None:
        if not self.output_key:
            self.output_key = f"task_{self.id}_result"


class Plan(BaseModel):
    """The full analysis plan: a sequence of tasks."""
    user_query: str
    reasoning: str = Field(default="", description="Why the plan was decomposed this way")
    tasks: list[Task] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Schema context
# ---------------------------------------------------------------------------


class ColumnInfo(BaseModel):
    """Metadata about a single database column."""
    name: str
    type: str
    description: str = ""
    notes: str = ""
    example_value: str = ""
    is_sensitive: bool = False


class TableInfo(BaseModel):
    """Metadata about a single database table."""
    name: str
    description: str = ""
    business_purpose: str = ""
    columns: list[ColumnInfo] = Field(default_factory=list)


class RelationInfo(BaseModel):
    """A foreign key relationship between two tables."""
    from_table: str
    from_column: str
    to_table: str
    to_column: str


class RetrievedSchema(BaseModel):
    """Schema context retrieved for a specific task."""
    tables: list[TableInfo] = Field(default_factory=list)
    relations: list[RelationInfo] = Field(default_factory=list)
    task_id: int | None = None


# ---------------------------------------------------------------------------
# SQL Generation
# ---------------------------------------------------------------------------


class SQLAttempt(BaseModel):
    """A single SQL generation attempt."""
    attempt_number: int
    sql: str
    reasoning: str = ""
    expected_output_shape: str = ""


class FewShotExample(BaseModel):
    """A (task, SQL) exemplar in the few-shot library."""
    task_text: str
    sql: str
    output_shape: str = ""
    tags: list[str] = Field(default_factory=list)
    success_count: int = 1  # incremented each time this exemplar helps


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class ExecutionResult(BaseModel):
    """The result of executing SQL against the sandbox."""
    status: ExecutionStatus
    task_id: int | None = None
    sql: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    error: str | None = None
    error_class: ErrorClass | None = None

    @property
    def is_ok(self) -> bool:
        return self.status == ExecutionStatus.OK

    @classmethod
    def ok_result(
        cls,
        task_id: int,
        sql: str,
        columns: list[str],
        rows: list[list[Any]],
    ) -> ExecutionResult:
        return cls(
            status=ExecutionStatus.OK,
            task_id=task_id,
            sql=sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
        )

    @classmethod
    def error_result(
        cls,
        task_id: int,
        sql: str,
        error: str,
        error_class: ErrorClass = ErrorClass.UNKNOWN,
    ) -> ExecutionResult:
        return cls(
            status=ExecutionStatus.ERROR,
            task_id=task_id,
            sql=sql,
            error=error,
            error_class=error_class,
        )

    def summary(self) -> str:
        """A compact summary for passing as upstream context."""
        if self.status == ExecutionStatus.ERROR:
            return f"[Error] {self.error}"
        cols = ", ".join(self.columns[:5])
        extra = f" +{len(self.columns) - 5} cols" if len(self.columns) > 5 else ""
        return (
            f"{self.row_count} rows × {len(self.columns)} cols "
            f"[{cols}{extra}]. "
            f"First row: {self.rows[0][:3] if self.rows else 'N/A'}"
        )


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------


class CriticVerdict(BaseModel):
    """The critic's judgment on whether an execution result is acceptable."""
    acceptable: bool
    feedback: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    null_ratio: float | None = None
    issues: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------


class ChartSpec(BaseModel):
    """Specification for a chart to render."""
    chart_type: Literal["line", "bar", "horizontal_bar", "stacked_bar",
                        "heatmap", "histogram", "scatter", "pie", "none"]
    x_column: str = ""
    y_column: str = ""
    value_column: str = ""   # for heatmap
    title: str = ""
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------


class NarrativeResult(BaseModel):
    """Generated narrative insights."""
    text: str
    grounded: bool = True
    unsupported_claims: list[str] = Field(default_factory=list)
    chart_description: str = ""


# ---------------------------------------------------------------------------
# Top-level output
# ---------------------------------------------------------------------------


class AnalysisOutput(BaseModel):
    """The complete output of an analysis run."""
    user_query: str
    status: str = "complete"  # "complete" | "failed"
    error_message: str = ""
    plan: Plan | None = None
    task_results: dict[int, ExecutionResult] = Field(default_factory=dict)
    charts: list[str] = Field(default_factory=list)  # file paths
    chart_specs: list[ChartSpec] | None = None
    narrative: NarrativeResult | None = None
    sql_log: list[SQLAttempt] = Field(default_factory=list)
    total_attempts: int = 0
    failed_tasks: list[int] = Field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# LLM response
# ---------------------------------------------------------------------------


class LLMResponse(BaseModel):
    """A structured LLM API response."""
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    duration_ms: float = 0.0
    finish_reason: str = "stop"
