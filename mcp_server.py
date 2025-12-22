#!/usr/bin/env python3
"""
MCP server exposing documentation search tools.

Tools:
- search_docs: Hybrid keyword + semantic search
- get_chunk: Retrieve specific chunk by ID
- list_sources: List indexed source files
"""

import argparse
import logging
import sqlite3
import struct
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Global database connection
_conn: sqlite3.Connection | None = None
_has_vec: bool = False
_embedding_model = None
_model_name: str = "BAAI/bge-small-en-v1.5"


def get_connection() -> sqlite3.Connection:
    """Get the database connection."""
    if _conn is None:
        raise RuntimeError("Database not initialized")
    return _conn


def get_embedding_model():
    """Lazy-load the embedding model."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(_model_name)
    return _embedding_model


def search_fts(query: str, limit: int) -> list[tuple[str, float]]:
    """Full-text search using FTS5. Returns (chunk_id, score) pairs."""
    conn = get_connection()

    # BM25 scoring (lower is better in FTS5, so we negate)
    results = conn.execute(
        """
        SELECT c.id, -bm25(chunks_fts, 1, 10) as score
        FROM chunks_fts
        JOIN chunks c ON chunks_fts.rowid = c.rowid
        WHERE chunks_fts MATCH ?
        ORDER BY score DESC
        LIMIT ?
    """,
        (query, limit),
    ).fetchall()

    return results


def search_vec(query: str, limit: int) -> list[tuple[str, float]]:
    """Vector similarity search. Returns (chunk_id, score) pairs."""
    if not _has_vec:
        return []

    conn = get_connection()

    try:
        model = get_embedding_model()
        query_embedding = model.encode([query])[0]
        embedding_blob = struct.pack(f"{len(query_embedding)}f", *query_embedding)

        results = conn.execute(
            """
            SELECT id, distance
            FROM chunks_vec
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
        """,
            (embedding_blob, limit),
        ).fetchall()

        # Convert distance to similarity score (higher is better)
        return [(id, 1 / (1 + dist)) for id, dist in results]
    except Exception as e:
        logger.warning(f"Vector search error: {e}")
        return []


def reciprocal_rank_fusion(
    results_lists: list[list[tuple[str, float]]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """
    Combine multiple ranked lists using Reciprocal Rank Fusion.

    RRF score = sum(1 / (k + rank_i)) for each list where item appears
    """
    scores: dict[str, float] = {}

    for results in results_lists:
        for rank, (chunk_id, _) in enumerate(results):
            rrf_score = 1.0 / (k + rank + 1)  # rank is 0-indexed
            scores[chunk_id] = scores.get(chunk_id, 0) + rrf_score

    # Sort by combined score
    sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results


def get_chunk_details(chunk_ids: list[str]) -> list[dict]:
    """Fetch full chunk details for given IDs."""
    conn = get_connection()

    placeholders = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"""
        SELECT id, source, title, content, chunk_index
        FROM chunks
        WHERE id IN ({placeholders})
    """,
        chunk_ids,
    ).fetchall()

    # Preserve order from chunk_ids
    id_to_row = {row[0]: row for row in rows}
    results = []
    for chunk_id in chunk_ids:
        if chunk_id in id_to_row:
            row = id_to_row[chunk_id]
            results.append(
                {
                    "chunk_id": row[0],
                    "source": row[1],
                    "title": row[2],
                    "content": row[3],
                    "chunk_index": row[4],
                }
            )

    return results


def search_docs_impl(query: str, limit: int = 10, mode: str = "hybrid") -> list[dict]:
    """
    Search documentation.

    Args:
        query: Search query
        limit: Maximum results to return
        mode: "keyword", "semantic", or "hybrid"

    Returns:
        List of matching chunks with scores
    """
    results_lists = []

    if mode in ("keyword", "hybrid"):
        fts_results = search_fts(query, limit)
        if fts_results:
            results_lists.append(fts_results)

    if mode in ("semantic", "hybrid") and _has_vec:
        vec_results = search_vec(query, limit)
        if vec_results:
            results_lists.append(vec_results)

    if not results_lists:
        return []

    # Combine results
    if len(results_lists) == 1:
        combined = results_lists[0][:limit]
        chunk_ids = [chunk_id for chunk_id, _ in combined]
        scores = {chunk_id: score for chunk_id, score in combined}
    else:
        combined = reciprocal_rank_fusion(results_lists)[:limit]
        chunk_ids = [chunk_id for chunk_id, _ in combined]
        scores = {chunk_id: score for chunk_id, score in combined}

    # Fetch full chunk details
    chunks = get_chunk_details(chunk_ids)

    # Add scores
    for chunk in chunks:
        chunk["score"] = scores.get(chunk["chunk_id"], 0)

    return chunks


def get_chunk_impl(chunk_id: str) -> dict | None:
    """Get a specific chunk by ID."""
    conn = get_connection()

    row = conn.execute(
        """
        SELECT id, source, title, content, chunk_index
        FROM chunks
        WHERE id = ?
    """,
        (chunk_id,),
    ).fetchone()

    if row:
        return {
            "chunk_id": row[0],
            "source": row[1],
            "title": row[2],
            "content": row[3],
            "chunk_index": row[4],
        }
    return None


def list_sources_impl() -> list[dict]:
    """List all indexed source files."""
    conn = get_connection()

    rows = conn.execute("""
        SELECT source, COUNT(*) as chunk_count
        FROM chunks
        GROUP BY source
        ORDER BY source
    """).fetchall()

    return [{"path": row[0], "chunk_count": row[1]} for row in rows]


def init_db(db_path: Path) -> None:
    """Initialize database connection."""
    global _conn, _has_vec

    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")

    # Try to load sqlite-vec
    try:
        import sqlite_vec

        _conn.enable_load_extension(True)
        sqlite_vec.load(_conn)
        _conn.enable_load_extension(False)
        _has_vec = True
    except Exception as e:
        logger.warning(f"sqlite-vec not available: {e}")
        logger.warning("Semantic search disabled, keyword search only.")
        _has_vec = False


def close_db() -> None:
    """Close the database connection."""
    global _conn
    if _conn is not None:
        try:
            # Checkpoint WAL to release file locks on Windows
            _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        _conn.close()
        _conn = None


def create_server() -> Server:
    """Create and configure the MCP server."""
    server = Server("docs-search")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="search_docs",
                description="Search documentation using keyword and/or semantic search",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results (default: 10)",
                            "default": 10,
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["keyword", "semantic", "hybrid"],
                            "description": "Search mode (default: hybrid)",
                            "default": "hybrid",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_chunk",
                description="Retrieve a specific documentation chunk by ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chunk_id": {
                            "type": "string",
                            "description": "The chunk identifier",
                        },
                    },
                    "required": ["chunk_id"],
                },
            ),
            Tool(
                name="list_sources",
                description="List all indexed documentation sources",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        import json

        if name == "search_docs":
            results = search_docs_impl(
                query=arguments["query"],
                limit=arguments.get("limit", 10),
                mode=arguments.get("mode", "hybrid"),
            )
            return [TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_chunk":
            result = get_chunk_impl(arguments["chunk_id"])
            if result:
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            else:
                return [TextContent(type="text", text="Chunk not found")]

        elif name == "list_sources":
            results = list_sources_impl()
            return [TextContent(type="text", text=json.dumps(results, indent=2))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return server


def test_search(db_path: Path, query: str) -> None:
    """Run a test search and print results."""
    init_db(db_path)

    print(f"Testing search: '{query}'\n")

    results = search_docs_impl(query, limit=5, mode="hybrid")

    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['score']:.4f}] {r['source']}")
        if r["title"]:
            print(f"   Title: {r['title']}")
        print(f"   {r['content'][:200]}...")
        print()


async def run_server(db_path: Path) -> None:
    """Run the MCP server."""
    init_db(db_path)
    server = create_server()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description="MCP server for documentation search")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("docs.db"),
        help="Path to the SQLite database",
    )
    parser.add_argument(
        "--test",
        type=str,
        help="Run a test search instead of starting the server",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="BAAI/bge-small-en-v1.5",
        help="Embedding model for semantic search",
    )

    args = parser.parse_args()

    global _model_name
    _model_name = args.model

    if not args.db.exists():
        logger.error(f"Database not found: {args.db}")
        logger.error("Run build_index.py first to create the database.")
        sys.exit(1)

    if args.test:
        test_search(args.db, args.test)
    else:
        import asyncio

        asyncio.run(run_server(args.db))


if __name__ == "__main__":
    main()
