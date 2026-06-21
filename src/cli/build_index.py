"""CLI: Build the Schema RAG index.

Usage:
    python -m src.cli.build_index        # Build with defaults
    python -m src.cli.build_index --rebuild  # Force rebuild
"""

from __future__ import annotations


def main() -> None:
    """Build (or rebuild) the Schema RAG index."""
    import argparse

    parser = argparse.ArgumentParser(description="Build Schema RAG index")
    parser.add_argument("--rebuild", action="store_true", help="Force rebuild")
    parser.add_argument("--config", type=str, default=None, help="Config path")
    args = parser.parse_args()

    from src.core.config import load_config
    from src.schema_rag.retriever import SchemaRetriever
    from src.schema_rag.chunker import chunk_schema_metadata

    config = load_config(args.config)

    print("Loading schema metadata...")
    chunks = chunk_schema_metadata()
    print(f"  Created {len(chunks)} chunks")

    print("Initializing SchemaRetriever...")
    retriever = SchemaRetriever(config)
    retriever.initialize(force_rebuild=args.rebuild)

    print(f"  ChromaDB collection size: {retriever._chroma.count()}")
    print("Index build complete. Ready for analysis.")
    print(f"  Run: python -m src.cli.analyze \"your question\"")


if __name__ == "__main__":
    main()
