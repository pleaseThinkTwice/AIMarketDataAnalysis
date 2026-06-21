"""Tests for chart type selection rules (deterministic, no LLM needed)."""

import pytest
from src.core.schemas import Task, ExecutionResult, ChartSpec
from src.visualization.chart_selector import ChartSelector


@pytest.fixture
def selector():
    return ChartSelector()


@pytest.fixture
def sample_task():
    return Task(id=1, goal="test visualization", expected_output_type="visualization")


class TestChartSelector:
    """Test that chart selection rules produce correct types."""

    def test_time_numeric_becomes_line(self, selector, sample_task):
        result = ExecutionResult.ok_result(1, "SELECT 1", ["date", "revenue"], [
            ["2017-01", 1000], ["2017-02", 1200], ["2017-03", 1100],
        ])
        spec = selector.select(result, sample_task)
        assert spec.chart_type == "line", f"Expected line, got {spec.chart_type}"

    def test_category_numeric_becomes_bar(self, selector, sample_task):
        # 8 categories is more than pie (≤7) but less than horizontal_bar (>10)
        result = ExecutionResult.ok_result(1, "SELECT 1", ["category", "count"], [
            ["electronics", 100], ["books", 80], ["clothing", 60], ["food", 50],
            ["toys", 40], ["sports", 30], ["beauty", 20], ["home", 10],
        ])
        spec = selector.select(result, sample_task)
        assert spec.chart_type == "bar", f"Expected bar, got {spec.chart_type}"

    def test_long_category_becomes_horizontal_bar(self, selector, sample_task):
        result = ExecutionResult.ok_result(1, "SELECT 1", ["state", "customers"], [
            ["SP", 5000], ["RJ", 3000], ["MG", 2500], ["RS", 2000],
            ["PR", 1800], ["BA", 1500], ["SC", 1200], ["DF", 1000],
            ["GO", 900], ["PE", 800], ["CE", 700],
        ])
        spec = selector.select(result, sample_task)
        assert spec.chart_type == "horizontal_bar", f"Expected horizontal_bar, got {spec.chart_type}"

    def test_two_category_numeric_becomes_heatmap(self, selector, sample_task):
        result = ExecutionResult.ok_result(1, "SELECT 1", ["category", "state", "amount"], [
            ["electronics", "SP", 5000], ["electronics", "RJ", 3000],
            ["books", "SP", 2000], ["books", "RJ", 1500],
        ])
        spec = selector.select(result, sample_task)
        assert spec.chart_type == "heatmap", f"Expected heatmap, got {spec.chart_type}"

    def test_single_numeric_becomes_histogram(self, selector, sample_task):
        rows = [[float(i * 10)] for i in range(50)]
        result = ExecutionResult.ok_result(1, "SELECT 1", ["price"], rows)
        spec = selector.select(result, sample_task)
        assert spec.chart_type == "histogram", f"Expected histogram, got {spec.chart_type}"

    def test_two_numeric_becomes_scatter(self, selector, sample_task):
        rows = [[float(i), float(i * 2)] for i in range(20)]
        result = ExecutionResult.ok_result(1, "SELECT 1", ["weight", "price"], rows)
        spec = selector.select(result, sample_task)
        assert spec.chart_type == "scatter", f"Expected scatter, got {spec.chart_type}"

    def test_few_category_becomes_pie(self, selector, sample_task):
        result = ExecutionResult.ok_result(1, "SELECT 1", ["type", "amount"], [
            ["credit_card", 500], ["boleto", 300], ["debit_card", 200],
        ])
        spec = selector.select(result, sample_task)
        assert spec.chart_type == "pie", f"Expected pie, got {spec.chart_type}"

    def test_empty_result_returns_none(self, selector, sample_task):
        result = ExecutionResult.ok_result(1, "SELECT 1", ["x"], [])
        spec = selector.select(result, sample_task)
        assert spec.chart_type == "none"
