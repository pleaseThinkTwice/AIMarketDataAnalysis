"""Tests for error classifier (deterministic, regex-based)."""

import pytest
from src.correction.classifier import ErrorClassifier
from src.core.schemas import ErrorClass


class TestErrorClassifier:
    """Test that error classification correctly categorizes DB errors."""

    def test_syntax_error(self):
        cls = ErrorClassifier.classify("syntax error at or near 'SELECT'")
        assert cls == ErrorClass.SYNTAX

    def test_schema_table_error(self):
        cls = ErrorClassifier.classify("relation 'orderz' does not exist")
        assert cls == ErrorClass.SCHEMA

    def test_schema_column_error(self):
        cls = ErrorClassifier.classify("column 'amont' does not exist")
        assert cls == ErrorClass.SCHEMA

    def test_type_error_operator(self):
        cls = ErrorClassifier.classify("operator does not exist: character varying + integer")
        assert cls == ErrorClass.TYPE

    def test_type_error_cast(self):
        cls = ErrorClassifier.classify("cannot cast type varchar to numeric")
        assert cls == ErrorClass.TYPE

    def test_type_error_function(self):
        cls = ErrorClassifier.classify("function sum(text) does not exist")
        assert cls == ErrorClass.TYPE

    def test_unknown_error(self):
        cls = ErrorClassifier.classify("connection timeout after 30000ms")
        assert cls == ErrorClass.UNKNOWN

    def test_empty_error(self):
        cls = ErrorClassifier.classify("")
        assert cls == ErrorClass.UNKNOWN

    def test_extract_table_name(self):
        name = ErrorClassifier.extract_entity("relation 'orderz' does not exist")
        assert name == "orderz"

    def test_extract_column_name(self):
        name = ErrorClassifier.extract_entity("column 'amont' does not exist")
        assert name == "amont"

    def test_extract_none_for_unknown(self):
        name = ErrorClassifier.extract_entity("something went wrong")
        assert name is None
