# Local Documentation Retrieval via MCP

A local, open-source system for making engineering documentation searchable by LLM coding assistants (Cursor, Claude Code, Codex CLI). Uses SQLite for storage, FTS5 for keyword search, and vector embeddings for semantic search.

## Design Principles

- Single SQLite file — No external services, no Docker
- No local LLM — Retrieval only; reasoning stays with the host LLM
- MCP protocol — Native support in Cursor, Claude Code, and Codex CLI
- uv for Python — Reproducible, friction-free environment management

## Why This Architecture

Hybrid search gives you the best of both worlds. FTS5 handles exact matches—API names, error messages, symbols. Embeddings handle vocabulary mismatch—when someone searches "make grid finer near edges" instead of "mesh refinement," or "simulation stuck" instead of "convergence tolerance."

SQLite FTS5 + sqlite-vec keeps everything in one file. No vector database to operate.

What this replaces: grep (too weak for ranking), Qdrant/Weaviate (operational overhead), local LLMs (slow, no accuracy benefit for retrieval).

## Requirements

- Python 3.11+
- SQLite 3.35+ (ships with Python)
- pandoc (for HTML→Markdown conversion)
- ~500MB disk for a typical docs corpus + embeddings

## Quick Start

```bash
# Clone and enter directory
git clone <repo-url> && cd local-docs-mcp

# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Initialize environment and install dependencies
uv sync

# Convert your HTML docs to Markdown (see Comsol example below)
./scripts/convert_html.sh /path/to/html/docs ./markdown

# Build index WITHOUT embeddings first (fast, for testing)
uv run python build_index.py ./markdown --output docs.db --no-embeddings

# Test that search works
uv run python mcp_server.py --db docs.db --test "your query here"

# Once satisfied, rebuild WITH embeddings (required for production use)
uv run python build_index.py ./markdown --output docs.db

# Run the MCP server
uv run python mcp_server.py --db docs.db

# Configure your IDE (see below)
```

## Example: Comsol Documentation

Comsol 6.4's HTML documentation is installed by default on Windows at:

```
C:\Program Files\COMSOL\COMSOL64\Multiphysics\doc\help\wtpwebapps\ROOT\doc\
```

The HTML files are spread across subdirectories (e.g., `comsol_ref_manual/`, `acdc_module/`, etc.).

### Windows (PowerShell)

The conversion script requires bash. Use Git Bash (included with Git for Windows) or WSL:

```powershell
# From Git Bash
./scripts/convert_html.sh "/c/Program Files/COMSOL/COMSOL64/Multiphysics/doc/help/wtpwebapps/ROOT/doc" ./markdown

# From WSL
./scripts/convert_html.sh "/mnt/c/Program Files/COMSOL/COMSOL64/Multiphysics/doc/help/wtpwebapps/ROOT/doc" ./markdown

# Build index (no embeddings for initial test)
uv run python build_index.py ./markdown --output comsol.db --no-embeddings

# Test search
uv run python mcp_server.py --db comsol.db --test "mesh refinement"

# Rebuild with embeddings for production
uv run python build_index.py ./markdown --output comsol.db
```

### macOS/Linux (if Comsol installed locally)

```bash
# Typical Linux path
./scripts/convert_html.sh /usr/local/comsol/multiphysics/doc/help/wtpwebapps/ROOT/doc ./markdown

# Or copy docs from Windows machine first
./scripts/convert_html.sh ./comsol_docs_copy ./markdown

# Build and test
uv run python build_index.py ./markdown --output comsol.db --no-embeddings
uv run python mcp_server.py --db comsol.db --test "boundary conditions"

# Production build with embeddings
uv run python build_index.py ./markdown --output comsol.db
```

### Expected Output

A typical Comsol installation produces:
- ~8,000–15,000 HTML files
- ~20,000–40,000 chunks after indexing
- ~50–150 MB database with embeddings
- ~5–10 minutes for full rebuild with embeddings

## Project Structure

```
local-docs-mcp/
├── pyproject.toml      # Dependencies and project config
├── build_index.py      # Indexing script
├── mcp_server.py       # MCP server exposing search tools
├── scripts/
│   └── convert_html.sh # HTML to Markdown conversion
├── markdown/           # Converted docs (gitignored)
└── docs.db             # SQLite database (gitignored)
```

## Detailed Setup

### 1. Install System Dependencies

macOS (Homebrew):
```bash
brew install python pandoc
```

Ubuntu/Debian:
```bash
sudo apt install python3 python3-pip pandoc
```

Windows (scoop):
```powershell
scoop install python pandoc git
```

### 2. Initialize the Project

```bash
uv sync
```

This reads `pyproject.toml` and installs all dependencies into a local `.venv`.

### 3. Convert HTML Documentation to Markdown

The included script handles batch conversion:

```bash
./scripts/convert_html.sh /path/to/source/html ./markdown
```

What it does:
- Recursively finds all `.html` and `.htm` files
- Converts each to GitHub-Flavored Markdown via pandoc
- Preserves directory structure
- Strips `.html` extension (so `api/mesh.html` → `api/mesh.md`)

For other source formats, adjust the pandoc command:
```bash
# From RST (Sphinx docs)
pandoc -f rst -t gfm input.rst -o output.md

# From DOCX
pandoc -f docx -t gfm input.docx -o output.md
```

### 4. Build the Search Index

For initial testing (fast, seconds):
```bash
uv run python build_index.py ./markdown --output docs.db --no-embeddings
```

For production use (with embeddings, minutes):
```bash
uv run python build_index.py ./markdown --output docs.db
```

Embeddings enable semantic search—finding "mesh refinement" when someone searches "make grid finer." Without embeddings, only exact keyword matching works. Always use embeddings for actual team usage.

Options:
```
--output PATH       Output database path (default: docs.db)
--chunk-size N      Target chunk size in characters (default: 1500)
--chunk-overlap N   Overlap between chunks (default: 200)
--embedding-model   Model name (default: BAAI/bge-small-en-v1.5)
--no-embeddings     Skip embedding generation (testing/debugging only)
--verbose           Show progress details
```

Rebuild vs. incremental: The script hashes files and skips unchanged content. A full rebuild of ~10k pages takes ~5 minutes with embeddings.

### 5. Test the MCP Server Locally

```bash
uv run python mcp_server.py --db docs.db
```

The server communicates via stdio. For testing, you can pipe JSON-RPC messages, but it's easier to just configure your IDE and test there.

## IDE Configuration

### Cursor

Create or edit `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "docs": {
      "command": "uv",
      "args": ["run", "python", "/absolute/path/to/mcp_server.py", "--db", "/absolute/path/to/docs.db"],
      "cwd": "/absolute/path/to/local-docs-mcp"
    }
  }
}
```

Restart Cursor after saving. The tools appear in the model's available tools.

### Claude Code

Add to your Claude Code MCP configuration:

```json
{
  "mcpServers": {
    "docs": {
      "command": "uv",
      "args": ["run", "python", "mcp_server.py", "--db", "docs.db"],
      "cwd": "/absolute/path/to/local-docs-mcp"
    }
  }
}
```

### Codex CLI

Configure via `~/.codex/config.json` or use the CLI:

```bash
codex mcp add docs "uv run python /path/to/mcp_server.py --db /path/to/docs.db"
```

## MCP Tools Exposed

### `search_docs`

Hybrid keyword + semantic search.

Parameters:
- `query` (string, required): Search query
- `limit` (integer, default 10): Max results to return
- `mode` (string, default "hybrid"): One of "keyword", "semantic", or "hybrid"

Returns: Array of objects with `chunk_id`, `source`, `title`, `content`, `score`

Example:
```json
{
  "query": "mesh refinement convergence",
  "limit": 5,
  "mode": "hybrid"
}
```

### `get_chunk`

Retrieve a specific chunk by ID (for follow-up after search).

Parameters:
- `chunk_id` (string, required): The chunk identifier

Returns: Object with full chunk content and metadata

### `list_sources`

List all indexed source files.

Returns: Array of source paths with chunk counts

## Search Behavior

### Hybrid Search (default)

Combines FTS5 keyword matching with vector similarity using Reciprocal Rank Fusion (RRF):

```
score = Σ 1/(k + rank_i)
```

Where `k=60` (standard RRF constant) and `rank_i` is the rank from each method.

This surfaces results that match either exact terms OR semantic meaning, with results appearing in both ranked highest.

### Keyword-Only Mode

Uses SQLite FTS5 with BM25 ranking. Best for:
- API names and symbols
- Error messages
- Exact phrase matching

### Semantic-Only Mode

Uses cosine similarity on embeddings. Handles vocabulary mismatch:
- "make grid finer near edges" → finds "mesh refinement"
- "simulation stuck" → finds convergence, solver tolerance
- "how do I set up walls" → finds boundary conditions

Essential for users who don't know exact terminology.

## Database Schema

```sql
-- Document chunks with metadata
CREATE TABLE chunks (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,          -- Original file path
    title TEXT,                    -- Extracted section title
    content TEXT NOT NULL,         -- Chunk text
    chunk_index INTEGER,           -- Position within source
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- FTS5 full-text index
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    content,
    title,
    content=chunks,
    content_rowid=rowid
);

-- Vector embeddings (via sqlite-vec)
CREATE VIRTUAL TABLE chunks_vec USING vec0(
    embedding float[384]           -- Dimension matches model
);

-- Source file tracking for incremental updates
CREATE TABLE sources (
    path TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Chunking Strategy

Documents are split using a header-aware algorithm:

1. Primary split: Markdown headers (`##`, `###`, etc.)
2. Secondary split: If a section exceeds `chunk_size`, split on paragraph boundaries
3. Tertiary split: If still too large, split on sentence boundaries
4. Overlap: Each chunk includes `chunk_overlap` characters from the previous chunk's end

Section titles are preserved as metadata for better context in search results.

## Maintenance

### When Documentation Updates

```bash
# Re-convert changed HTML files
./scripts/convert_html.sh /path/to/html ./markdown

# Rebuild index with embeddings (incremental—skips unchanged files)
uv run python build_index.py ./markdown --output docs.db

# Restart MCP server (or it picks up changes on next query)
```

### Validation

```bash
# Check database integrity
uv run python -c "
import sqlite3
conn = sqlite3.connect('docs.db')
print(f'Chunks: {conn.execute(\"SELECT COUNT(*) FROM chunks\").fetchone()[0]}')
print(f'Sources: {conn.execute(\"SELECT COUNT(*) FROM sources\").fetchone()[0]}')
"

# Test search from command line
uv run python mcp_server.py --db docs.db --test "boundary conditions"
```

## Troubleshooting

### "sqlite-vec extension not found"

sqlite-vec requires compilation on some platforms. Try:

```bash
# Usually works via pip
uv add sqlite-vec --reinstall

# If that fails on macOS
brew install sqlite
uv add sqlite-vec --reinstall
```

### "No results for queries that should match"

1. Check the content was indexed: `SELECT COUNT(*) FROM chunks WHERE content LIKE '%yourterm%'`
2. FTS5 tokenization may differ from your expectation. Try simpler queries.
3. For code symbols, ensure they weren't stripped during HTML→Markdown conversion.

### "MCP server not connecting"

1. Test manually: `uv run python mcp_server.py --db docs.db` should start without errors
2. Check paths in IDE config are absolute
3. Check `cwd` is set correctly
4. Look at IDE's MCP debug logs

### Slow indexing

Embedding generation is the bottleneck (~5 min for 10k chunks). Options:
- Use `--no-embeddings` for initial testing, then rebuild with embeddings
- Use a smaller model (trades accuracy for speed)
- Run on a machine with GPU (sentence-transformers auto-detects CUDA)

## License

MIT