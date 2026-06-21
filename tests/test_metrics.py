"""Tests for evaluation metrics (deterministic, pure math)."""

import pytest
from src.evaluation.metrics import (
    execution_accuracy, component_match, task_success_rate,
    correction_lift, avg_attempts,
)


class TestExecutionAccuracy:
    def test_exact_match(self):
        pred = [["a", 1], ["b", 2]]
        gold = [["a", 1], ["b", 2]]
        assert execution_accuracy(pred, gold)

    def test_row_order_independent(self):
        pred = [["b", 2], ["a", 1]]
        gold = [["a", 1], ["b", 2]]
        assert execution_accuracy(pred, gold)

    def test_mismatch_count(self):
        pred = [["a", 1]]
        gold = [["a", 1], ["b", 2]]
        assert not execution_accuracy(pred, gold)

    def test_both_empty(self):
        assert execution_accuracy([], [])

    def test_one_empty(self):
        assert not execution_accuracy([["a", 1]], [])

    def test_value_mismatch(self):
        pred = [["a", 1], ["b", 3]]
        gold = [["a", 1], ["b", 2]]
        assert not execution_accuracy(pred, gold)


class TestComponentMatch:
    def test_identical(self):
        sql = "SELECT a FROM t WHERE x = 1 ORDER BY a"
        assert component_match(sql, sql) == 1.0

    def test_completely_different(self):
        assert component_match("SELECT a", "INSERT INTO x") < 0.5

    def test_empty(self):
        assert component_match("", "") == 0.0


class TestTaskSuccessRate:
    def test_all_success(self):
        assert task_success_rate([True, True, True]) == 1.0

    def test_half_success(self):
        assert task_success_rate([True, False]) == 0.5

    def test_empty(self):
        assert task_success_rate([]) == 0.0


class TestCorrectionLift:
    def test_positive_lift(self):
        assert correction_lift(0.79, 0.71) == pytest.approx(0.08)


class TestAvgAttempts:
    def test_average(self):
        assert avg_attempts([1, 2, 3]) == 2.0

    def test_empty(self):
        assert avg_attempts([]) == 0.0
