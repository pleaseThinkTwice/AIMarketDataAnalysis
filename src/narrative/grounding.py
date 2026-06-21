"""Narrative grounding verification.

Checks that numeric claims made in LLM-generated narratives are supported
by the original query results. Reuses the 3-gram backtracking pattern from
the RAG movie project, adapted for numeric claims.
"""

from __future__ import annotations

import re


def extract_numeric_claims(text: str) -> list[dict[str, str]]:
    """Extract numeric claims from narrative text.

    Returns list of dicts with 'value' and 'context'.
    Example: "退货率为 12.5%" → {"value": "12.5%", "context": "退货率"}
    """
    claims = []
    # Match patterns like "XX%" or "XX 元" or "XX 个"
    patterns = [
        (r'(\d+\.?\d*\s*%)', 'percentage'),
        (r'(\d+\.?\d*\s*元)', 'currency'),
        (r'(\d+\.?\d*\s*个)', 'count'),
    ]
    for pattern, claim_type in patterns:
        for match in re.finditer(pattern, text):
            start = max(0, match.start() - 20)
            context = text[start:match.end() + 10]
            claims.append({"value": match.group(1), "type": claim_type, "context": context})
    return claims


def verify_grounding(claims: list[dict], source_data: str) -> list[str]:
    """Check which claims are NOT supported by source data.

    Returns list of unsupported claim values.
    """
    unsupported = []
    for claim in claims:
        val = claim["value"].strip().replace("%", "").replace("元", "").replace("个", "").strip()
        if val not in source_data:
            unsupported.append(claim["value"])
    return unsupported
