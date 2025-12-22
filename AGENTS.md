# CLAUDE.md

> Context file for Claude Code and other LLM coding assistants.

## Project Overview

Local documentation retrieval system using MCP (Model Context Protocol). Indexes Markdown docs into SQLite with FTS5 keyword search and optional vector embeddings. Exposes search via MCP tools for use by Cursor, Claude Code, and Codex CLI.

## Architecture

```
HTML docs → pandoc → Markdown → build_index.py → SQLite DB → mcp_server.py → MCP tools
```

**Key files:**
- `build_index.py` — Indexes Markdown into SQLite (FTS5 + optional sqlite-vec embeddings)
- `mcp_server.py` — MCP server exposing `search_docs`, `get_chunk`, `list_sources` tools
- `scripts/convert_html.sh` — Batch HTML→Markdown conversion via pandoc

**Database schema:**
- `chunks` — Document chunks with id, source, title, content, chunk_index
- `chunks_fts` — FTS5 virtual table for keyword search
- `chunks_vec` — sqlite-vec virtual table for embeddings (optional)
- `sources` — File path → hash mapping for incremental updates

## Common Tasks

### Run tests
```bash
uv run pytest tests/ -v
```

### Run tests without embeddings (faster)
```bash
uv run pytest tests/ -v --ignore=tests/test_embeddings.py
```

### Lint and format
```bash
uv run ruff check .
uv run ruff format .
```

### Build index from Markdown
```bash
uv run python build_index.py ./markdown --output docs.db
```

### Build index without embeddings (faster)
```bash
uv run python build_index.py ./markdown --output docs.db --no-embeddings
```

### Test search from CLI
```bash
uv run python mcp_server.py --db docs.db --test "search query"
```

### Run MCP server
```bash
uv run python mcp_server.py --db docs.db
```

## Code Patterns

### Chunking strategy
Documents split on Markdown headers first, then paragraphs, then sentences. Configurable `chunk_size` (default 1500 chars) and `chunk_overlap` (default 200 chars).

### Hybrid search
Uses Reciprocal Rank Fusion (RRF) to combine FTS5 keyword results with vector similarity. RRF score: `sum(1/(k + rank))` where k=60.

### FTS5 sync
Triggers keep `chunks_fts` in sync with `chunks` table on INSERT/UPDATE/DELETE. No manual FTS management needed.

### Incremental indexing
`sources` table tracks file hashes. Re-running `build_index.py` skips unchanged files.

## Dependencies

- `mcp` — Model Context Protocol server library
- `sentence-transformers` — Embedding model (optional, for semantic search)
- `sqlite-vec` — SQLite vector extension (optional, for semantic search)
- `beautifulsoup4`, `lxml` — HTML parsing (used by pandoc output cleanup)

## Testing Notes

- Tests use temp directories and in-memory fixtures, no cleanup needed
- `conftest.py` has `sample_markdown_files` fixture with representative test docs
- CI skips embedding tests (slow model download) except on main branch
- sqlite-vec can be flaky on some platforms; keyword-only mode always works

## MCP Tool Signatures

### search_docs
```json
{
  "query": "string (required)",
  "limit": "integer (default 10)",
  "mode": "keyword | semantic | hybrid (default hybrid)"
}
```
Returns: `[{chunk_id, source, title, content, score}, ...]`

### get_chunk
```json
{
  "chunk_id": "string (required)"
}
```
Returns: `{chunk_id, source, title, content, chunk_index}` or null

### list_sources
```json
{}
```
Returns: `[{path, chunk_count}, ...]`
