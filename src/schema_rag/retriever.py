"""Top-level schema retriever: hybrid search + table expansion + PK/FK injection.

This is the main entry point used by the Agent to get task-relevant schema context.

Usage:
    retriever = SchemaRetriever(config)
    schema = retriever.retrieve("上季度退货率最高的品类")
    # schema.tables contains TableInfo objects ready for prompt rendering
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from src.core.schemas import TableInfo, ColumnInfo, RelationInfo, RetrievedSchema
from src.schema_rag.chunker import (
    SchemaChunk,
    chunk_schema_metadata,
    get_all_fields_by_table,
    ALWAYS_INJECT_FIELDS,
)
from src.schema_rag.embedder import get_embedder
from src.schema_rag.chroma_store import SchemaChromaStore
from src.schema_rag.bm25_retriever import BM25Retriever
from src.schema_rag.fusion import rrf_fuse


class SchemaRetriever:
    """Hybrid schema retriever: vector + BM25 → RRF fusion → table expansion."""

    def __init__(self, config: Any) -> None:
        self._config = config
        self._embedder = get_embedder(config)
        self._chroma = SchemaChromaStore()
        self._bm25 = BM25Retriever()
        self._chunks: list[SchemaChunk] = []
        self._fields_by_table: dict[str, list[SchemaChunk]] = {}
        self._metadata: dict[str, Any] = {}
        self._initialized = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self, force_rebuild: bool = False) -> None:
        """Load or build the schema index.

        Args:
            force_rebuild: If True, re-chunk and re-embed even if index exists.
        """
        if self._initialized and not force_rebuild:
            return

        # Load schema metadata
        meta_path = Path(__file__).resolve().parent.parent / "data" / "schema_metadata.json"
        with open(meta_path, "r", encoding="utf-8") as fh:
            self._metadata = json.load(fh)

        # Chunk
        self._chunks = chunk_schema_metadata(meta_path)
        self._fields_by_table = get_all_fields_by_table(self._chunks)

        # Build index if needed
        if force_rebuild or self._chroma.count() == 0:
            texts = [c.text for c in self._chunks]
            embeddings = self._embedder.encode(texts)
            self._chroma.build(self._chunks, embeddings)
            self._bm25.build(self._chunks)

            # Persist BM25
            bm25_path = Path("data/indexes/schema_bm25.pkl")
            self._bm25.save(bm25_path)
        else:
            # Try loading BM25
            bm25_path = Path("data/indexes/schema_bm25.pkl")
            if not self._bm25.load(bm25_path):
                self._bm25.build(self._chunks)
                self._bm25.save(bm25_path)

        self._initialized = True

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(
        self,
        task_description: str,
        top_k: int | None = None,
    ) -> RetrievedSchema:
        """Retrieve relevant schema context for a task.

        Args:
            task_description: Natural language task description.
            top_k: Number of chunks to retrieve (default from config).

        Returns:
            RetrievedSchema with tables, fields, and relations.
        """
        if not self._initialized:
            self.initialize()

        if top_k is None:
            top_k = self._config.schema_rag.chunk.top_k

        # 1. Embed query
        query_vec = self._embedder.encode_single(task_description)

        # 2. Vector search
        vector_results = self._chroma.query(query_vec, top_k=top_k * 2)

        # 3. BM25 search
        bm25_results = self._bm25.search(task_description, top_k=top_k * 2)

        # 4. RRF fusion
        fused = rrf_fuse(
            vector_results,
            bm25_results,
            k=self._config.schema_rag.fusion.rrf_k,
            top_k=top_k,
            vector_weight=self._config.schema_rag.fusion.vector_weight,
            bm25_weight=self._config.schema_rag.fusion.bm25_weight,
        )

        # 5. Table-level expansion + PK/FK injection
        return self._assemble_schema(fused)

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------

    def _assemble_schema(self, fused_chunks: list[dict[str, Any]]) -> RetrievedSchema:
        """Assemble a RetrievedSchema from fused retrieval results.

        Applies two post-processing steps:
        1. Table-level expansion: if any field from a table is in results,
           include ALL fields from that table.
        2. PK/FK injection: always include core JOIN keys even if not retrieved.
        """
        # Gather which tables are hit
        tables_hit: set[str] = set()
        field_chunks_by_table: dict[str, set[str]] = {}

        for item in fused_chunks:
            table = item.get("table", "")
            if not table:
                continue
            if item.get("chunk_type") == "table":
                tables_hit.add(table)
            elif item.get("chunk_type") == "field":
                tables_hit.add(table)
                field_chunks_by_table.setdefault(table, set()).add(item.get("column", ""))
            elif item.get("chunk_type") == "relation":
                tables_hit.add(table)

        # Always inject core tables
        from src.schema_rag.chunker import ALWAYS_INJECT_TABLES
        tables_hit.update(ALWAYS_INJECT_TABLES)

        # Assemble TableInfo objects
        tables: list[TableInfo] = []
        relations: list[RelationInfo] = []

        for table_entry in self._metadata.get("tables", []):
            tname = table_entry["name"]
            if tname not in tables_hit:
                continue

            columns: list[ColumnInfo] = []
            for col_entry in table_entry.get("columns", []):
                cname = col_entry["name"]
                is_sensitive = col_entry.get("is_sensitive", False)
                if is_sensitive:
                    continue

                columns.append(ColumnInfo(
                    name=cname,
                    type=col_entry.get("type", ""),
                    description=col_entry.get("description", ""),
                    notes=col_entry.get("notes", ""),
                    example_value=col_entry.get("example_value", ""),
                    is_sensitive=is_sensitive,
                ))

            tables.append(TableInfo(
                name=tname,
                description=table_entry.get("description", ""),
                business_purpose=table_entry.get("business_purpose", ""),
                columns=columns,
            ))

        # Assemble RelationInfo objects
        for rel in self._metadata.get("table_relationships", []):
            from_t = rel["from_table"]
            from_c = rel["from_column"]
            to_t = rel["to_table"]
            to_c = rel["to_column"]

            # Include if either side is in our tables
            if from_t in tables_hit or to_t in tables_hit:
                relations.append(RelationInfo(
                    from_table=from_t,
                    from_column=from_c,
                    to_table=to_t,
                    to_column=to_c,
                ))

        return RetrievedSchema(tables=tables, relations=relations)
