"""Shared test fixtures for the Data Analysis Agent."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def sample_config():
    """Return a minimal AppConfig for testing."""
    from src.core.config import load_config
    return load_config()


@pytest.fixture
def mock_llm_response():
    """Factory for creating mock LLMResponse objects."""
    from src.core.schemas import LLMResponse

    def _make(content: str = "", input_tokens: int = 100, output_tokens: int = 50):
        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model="test-model",
            duration_ms=100.0,
        )
    return _make


@pytest.fixture
def sample_execution_result():
    """Return a sample ExecutionResult for testing."""
    from src.core.schemas import ExecutionResult, ExecutionStatus
    return ExecutionResult(
        status=ExecutionStatus.OK,
        task_id=1,
        sql="SELECT * FROM orders WHERE is_deleted = 0 LIMIT 10",
        columns=["order_id", "amount", "created_at"],
        rows=[
            ["ord_001", 150.0, "2017-10-12 14:23:00"],
            ["ord_002", 89.90, "2017-10-13 09:15:00"],
            ["ord_003", 249.00, "2017-10-14 16:45:00"],
        ],
        row_count=3,
    )
