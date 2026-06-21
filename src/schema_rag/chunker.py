"""Structured chunking of schema metadata for RAG retrieval.

Produces three chunk types:
    - table-level: table_name | description | business_purpose
    - field-level: table.column | type | description | notes
    - relation: FK: from_table.from_col → to_table.to_col | note

Total: ~150 chunks for a 12-table / ~100-field schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Chunk data model (lightweight dict)
# ---------------------------------------------------------------------------

class SchemaChunk:
    """A single searchable schema chunk."""
    __slots__ = ("chunk_id", "chunk_type", "text", "table", "column")

    def __init__(
        self,
        chunk_id: str,
        chunk_type: str,  # "table" | "field" | "relation"
        text: str,
        table: str = "",
        column: str = "",
    ) -> None:
        self.chunk_id = chunk_id
        self.chunk_type = chunk_type
        self.text = text
        self.table = table
        self.column = column

    def to_dict(self) -> dict[str, str]:
        return {
            "chunk_id": self.chunk_id,
            "chunk_type": self.chunk_type,
            "text": self.text,
            "table": self.table,
            "column": self.column,
        }


# ---------------------------------------------------------------------------
# Chunking logic
# ---------------------------------------------------------------------------


def chunk_schema_metadata(
    metadata_path: str | Path | None = None,
) -> list[SchemaChunk]:
    """Parse schema_metadata.json and produce structured chunks.

    Args:
        metadata_path: Path to schema_metadata.json. If None, uses the
                       default location relative to this file.

    Returns:
        List of SchemaChunk objects (~150 for the full schema).
    """
    if metadata_path is None:
        metadata_path = (
            Path(__file__).resolve().parent.parent / "data" / "schema_metadata.json"
        )

    with open(metadata_path, "r", encoding="utf-8") as fh:
        meta = json.load(fh)

    chunks: list[SchemaChunk] = []

    # 1. Table-level chunks
    for table in meta.get("tables", []):
        tname = table["name"]
        tdesc = table.get("description", "")
        tpurpose = table.get("business_purpose", "")
        text = f"表 {tname} | {tdesc} | 业务用途: {tpurpose}"
        chunks.append(SchemaChunk(
            chunk_id=f"table:{tname}",
            chunk_type="table",
            text=text,
            table=tname,
        ))

        # 2. Field-level chunks
        for col in table.get("columns", []):
            cname = col["name"]
            ctype = col.get("type", "")
            cdesc = col.get("description", "")
            cnotes = col.get("notes", "")
            is_sensitive = col.get("is_sensitive", False)

            # Skip sensitive fields — LLM should never see them
            if is_sensitive:
                continue

            parts = [f"字段 {tname}.{cname} | 类型: {ctype} | {cdesc}"]
            if cnotes:
                parts.append(f"⚠️ 注意事项: {cnotes}")
            text = " | ".join(parts)

            chunks.append(SchemaChunk(
                chunk_id=f"field:{tname}.{cname}",
                chunk_type="field",
                text=text,
                table=tname,
                column=cname,
            ))

    # 3. Relation chunks (FK relationships)
    for rel in meta.get("table_relationships", []):
        from_t = rel["from_table"]
        from_c = rel["from_column"]
        to_t = rel["to_table"]
        to_c = rel["to_column"]
        note = rel.get("note", "")
        text = f"外键关系: {from_t}.{from_c} → {to_t}.{to_c}"
        if note:
            text += f" | {note}"
        chunks.append(SchemaChunk(
            chunk_id=f"relation:{from_t}.{from_c}→{to_t}.{to_c}",
            chunk_type="relation",
            text=text,
            table=from_t,
        ))

    return chunks


def get_all_fields_by_table(chunks: list[SchemaChunk]) -> dict[str, list[SchemaChunk]]:
    """Group field chunks by table name for the table-level expansion logic.

    Returns:
        Dict[table_name, list of field SchemaChunk].
    """
    result: dict[str, list[SchemaChunk]] = {}
    for chunk in chunks:
        if chunk.chunk_type == "field":
            result.setdefault(chunk.table, []).append(chunk)
    return result


# Hard-coded PK/FK whitelist — always inject these into schema context
# to prevent RAG misses from breaking JOINs.
ALWAYS_INJECT_TABLES: set[str] = {"orders", "order_items", "skus", "users", "categories"}

ALWAYS_INJECT_FIELDS: list[tuple[str, str]] = [
    # (table, column) — core JOIN keys
    ("orders", "order_id"),
    ("orders", "user_id"),
    ("order_items", "order_id"),
    ("order_items", "sku_id"),
    ("skus", "sku_id"),
    ("skus", "category_id"),
    ("users", "user_id"),
    ("categories", "category_id"),
    ("payments", "order_id"),
    ("returns", "order_id"),
    ("returns", "sku_id"),
    ("returns", "reason_id"),
    ("return_reasons", "reason_id"),
    ("reviews", "order_id"),
    ("reviews", "sku_id"),
    ("reviews", "user_id"),
    ("dim_order_status", "status_code"),
]
