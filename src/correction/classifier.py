"""Error classifier: categorizes database errors for targeted correction.

Classifies errors into four types:
    A. SYNTAX  — SQL parse/syntax errors (fixable via error message)
    B. SCHEMA  — Table/column doesn't exist (fixable via schema re-retrieval)
    C. TYPE    — Type mismatch (fixable via error message + schema)
    D. SEMANTIC — SQL runs but result is wrong (needs Critic, not this classifier)
"""

from __future__ import annotations

import re

from src.core.schemas import ErrorClass


class ErrorClassifier:
    """Classifies PostgreSQL error messages into structured ErrorClass values."""

    # Patterns for schema errors (table/column doesn't exist)
    SCHEMA_PATTERNS = [
        r"relation\s+[\"']?(\w+)[\"']?\s+does\s+not\s+exist",
        r"column\s+[\"']?(\w+)[\"']?\s+does\s+not\s+exist",
        r"column\s+[\"']?(.+?)[\"']?\s+cannot\s+be\s+found",
        r"missing\s+FROM-clause\s+entry\s+for\s+table",
    ]

    # Patterns for type errors
    TYPE_PATTERNS = [
        r"operator\s+does\s+not\s+exist:",
        r"cannot\s+compare",
        r"type\s+mismatch",
        r"invalid\s+input\s+syntax\s+for\s+type",
        r"function\s+\w+\(.*\)\s+does\s+not\s+exist",
        r"cannot\s+cast\s+type",
        r"UNION\s+types\s+\w+\s+and\s+\w+\s+cannot\s+be\s+matched",
    ]

    # Patterns for syntax errors
    SYNTAX_PATTERNS = [
        r"syntax\s+error",
        r"at\s+or\s+near",
        r"unterminated",
        r"unexpected\s+token",
    ]

    # Patterns for semantic hints (from critic feedback, not DB errors)
    SEMANTIC_PATTERNS = [
        r"row_count.*0",
        r"empty\s+result",
        r"wrong\s+result",
        r"missing\s+group\s+by",
        r"should\s+use\s+inner\s+join",
    ]

    @classmethod
    def classify(cls, error_message: str) -> ErrorClass:
        """Classify a database error message.

        Args:
            error_message: The raw error message from PostgreSQL or Critic.

        Returns:
            ErrorClass enum value.
        """
        if not error_message:
            return ErrorClass.UNKNOWN

        msg_lower = error_message.lower()

        # Check schema patterns first (most actionable)
        for pattern in cls.SCHEMA_PATTERNS:
            if re.search(pattern, msg_lower):
                return ErrorClass.SCHEMA

        # Check type patterns
        for pattern in cls.TYPE_PATTERNS:
            if re.search(pattern, msg_lower):
                return ErrorClass.TYPE

        # Check syntax patterns
        for pattern in cls.SYNTAX_PATTERNS:
            if re.search(pattern, msg_lower):
                return ErrorClass.SYNTAX

        # Check semantic patterns
        for pattern in cls.SEMANTIC_PATTERNS:
            if re.search(pattern, msg_lower):
                return ErrorClass.SEMANTIC

        return ErrorClass.UNKNOWN

    @classmethod
    def extract_entity(cls, error_message: str) -> str | None:
        """Extract the problematic table/column name from a schema error.

        Returns the entity name if found, None otherwise.
        """
        match = re.search(r"relation\s+[\"']?(\w+)[\"']?", error_message)
        if match:
            return match.group(1)
        match = re.search(r"column\s+[\"']?(\w+)[\"']?", error_message)
        if match:
            return match.group(1)
        return None
