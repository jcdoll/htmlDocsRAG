#!/usr/bin/env python3
"""MCP server exposing documentation search tools."""

import argparse
import logging
import sys
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from db import (
    get_chunk,
    get_chunk_by_title,
    get_context,
    get_data_dir,
    get_db_name,
    get_source,
    get_stats,
    init_db,
    list_databases,
    list_modules,
    list_sections,
    list_sources,
    resolve_db_path,
    search_docs,
    search_sources,
    search_symbols,
    search_titles,
    set_model_name,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def create_server() -> Server:
    """Create and configure the MCP server."""
    server = Server("docs-search")
    name = get_db_name()

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="search_docs",
                description=f"Search {name} documentation",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "default": 10},
                        "mode": {"type": "string", "enum": ["keyword", "semantic", "hybrid"]},
                        "source_filter": {
                            "type": "string",
                            "description": "Filter by source path substring (e.g., 'llmatlab')",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_stats",
                description=f"Get {name} database statistics",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="get_chunk",
                description=f"Get a {name} chunk by ID",
                inputSchema={
                    "type": "object",
                    "properties": {"chunk_id": {"type": "string"}},
                    "required": ["chunk_id"],
                },
            ),
            Tool(
                name="list_sources",
                description=f"List indexed {name} sources",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="list_modules",
                description=f"List {name} modules/products with file counts",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="search_sources",
                description=f"Search {name} source paths by substring",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Substring to match"},
                        "limit": {"type": "integer", "default": 50},
                    },
                    "required": ["pattern"],
                },
            ),
            Tool(
                name="get_context",
                description=f"Get a {name} chunk with surrounding context",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "chunk_id": {"type": "string"},
                        "before": {"type": "integer", "default": 1},
                        "after": {"type": "integer", "default": 1},
                    },
                    "required": ["chunk_id"],
                },
            ),
            Tool(
                name="get_source",
                description=f"Get all chunks from a {name} source file",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source_path": {"type": "string"},
                        "offset": {"type": "integer", "default": 0},
                        "limit": {"type": "integer"},
                    },
                    "required": ["source_path"],
                },
            ),
            Tool(
                name="list_sections",
                description=f"List all section titles in a {name} source file",
                inputSchema={
                    "type": "object",
                    "properties": {"source_path": {"type": "string"}},
                    "required": ["source_path"],
                },
            ),
            Tool(
                name="get_chunk_by_title",
                description=f"Get all chunks with a specific title from a {name} source file",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "source_path": {"type": "string"},
                        "title": {"type": "string", "description": "Section title to retrieve"},
                    },
                    "required": ["source_path", "title"],
                },
            ),
            Tool(
                name="search_symbols",
                description=f"Search for API/function symbols by prefix in {name} docs",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "prefix": {"type": "string", "description": "Symbol prefix (e.g., 'mph')"},
                        "limit": {"type": "integer", "default": 50},
                    },
                    "required": ["prefix"],
                },
            ),
            Tool(
                name="search_titles",
                description=f"Search section titles across all {name} sources",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Substring to match"},
                        "limit": {"type": "integer", "default": 50},
                    },
                    "required": ["pattern"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        import json

        handlers = {
            "search_docs": lambda: search_docs(
                arguments["query"],
                arguments.get("limit", 10),
                arguments.get("mode", "hybrid"),
                arguments.get("source_filter"),
            ),
            "get_stats": get_stats,
            "get_chunk": lambda: get_chunk(arguments["chunk_id"]) or "Chunk not found",
            "list_sources": list_sources,
            "list_modules": list_modules,
            "search_sources": lambda: search_sources(
                arguments["pattern"], arguments.get("limit", 50)
            ),
            "get_context": lambda: get_context(
                arguments["chunk_id"], arguments.get("before", 1), arguments.get("after", 1)
            ),
            "get_source": lambda: get_source(
                arguments["source_path"], arguments.get("offset", 0), arguments.get("limit")
            ),
            "list_sections": lambda: list_sections(arguments["source_path"]),
            "get_chunk_by_title": lambda: get_chunk_by_title(
                arguments["source_path"], arguments["title"]
            ),
            "search_symbols": lambda: search_symbols(
                arguments["prefix"], arguments.get("limit", 50)
            ),
            "search_titles": lambda: search_titles(
                arguments["pattern"], arguments.get("limit", 50)
            ),
        }
        result = handlers[name]() if name in handlers else f"Unknown tool: {name}"
        text = result if isinstance(result, str) else json.dumps(result, indent=2)
        return [TextContent(type="text", text=text)]

    return server


def test_search(db_path: Path, query: str, mode: str = "keyword") -> None:
    """Run a test search and print results."""
    init_db(db_path)
    print(f"Testing search: '{query}' (mode: {mode})\n")
    results = search_docs(query, limit=5, mode=mode)
    if not results:
        print("No results found.")
        return
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['score']:.4f}] {r['source']}")
        if r["title"]:
            print(f"   Title: {r['title']}")
        print(f"   {r['content'][:200]}...\n")


async def run_server(db_path: Path) -> None:
    """Run the MCP server."""
    init_db(db_path)
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    data_dir = get_data_dir()
    parser = argparse.ArgumentParser(
        description="MCP server for documentation search",
        epilog=f"Databases searched in: {data_dir}",
    )
    parser.add_argument("--db", type=str, help="Database name or path")
    parser.add_argument("--list", action="store_true", help="List available databases")
    parser.add_argument("--test", type=str, help="Run a test search")
    parser.add_argument("--mode", choices=["keyword", "semantic", "hybrid"], default="keyword")
    parser.add_argument("--model", type=str, default="BAAI/bge-small-en-v1.5")
    args = parser.parse_args()

    if args.list:
        dbs = list_databases()
        print(f"Databases in {data_dir}:" if dbs else f"No databases in {data_dir}")
        for db in dbs:
            print(f"  {db.name}")
        sys.exit(0)

    if not args.db:
        dbs = list_databases()
        if dbs:
            print("Available: " + ", ".join(db.name for db in dbs))
        parser.print_usage()
        sys.exit(1)

    set_model_name(args.model)
    db_path = resolve_db_path(args.db)
    if not db_path.exists():
        logger.error(f"Database not found: {args.db}")
        sys.exit(1)

    if args.test:
        test_search(db_path, args.test, args.mode)
    else:
        import asyncio
        asyncio.run(run_server(db_path))


if __name__ == "__main__":
    main()
