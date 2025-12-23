# Local Documentation Retrieval via MCP

Make engineering documentation searchable by LLM coding assistants (Claude Code, Cursor, Codex CLI). Uses SQLite FTS5 for keyword search and vector embeddings for semantic search. Single file, no external services.

## Why This Architecture

Hybrid search gives you the best of both worlds. FTS5 handles exact matches—API names, error messages, symbols. Embeddings handle vocabulary mismatch—when someone searches "make grid finer near edges" instead of "mesh refinement."

SQLite FTS5 + sqlite-vec keeps everything in one file. No vector database to operate, no Docker, no external services.

What this replaces: grep (no ranking), Qdrant/Weaviate (operational overhead), local LLMs (slow, no accuracy benefit for retrieval).

## Requirements

- Python 3.11+
- uv (recommended) or pip
- ~500MB disk for typical docs corpus + embeddings

## Quick Start (Pre-built Database)

macOS/Linux:
```bash
uv tool install https://github.com/jcdoll/htmlDocsRAG.git
mkdir -p ~/.local/share/docs-mcp
curl -L https://github.com/jcdoll/htmlDocsRAG/releases/latest/download/comsol.db -o ~/.local/share/docs-mcp/comsol.db
docs-mcp --db comsol.db --test "mesh refinement"
docs-mcp --help
```

Windows (PowerShell):
```powershell
uv tool install https://github.com/jcdoll/htmlDocsRAG.git
mkdir -Force "$env:LOCALAPPDATA\docs-mcp"
Invoke-WebRequest -Uri "https://github.com/jcdoll/htmlDocsRAG/releases/latest/download/comsol.db" -OutFile "$env:LOCALAPPDATA\docs-mcp\comsol.db"
docs-mcp --db comsol.db --test "mesh refinement"
docs-mcp --help
```

You next need to plug it into your favorite IDE. There are two steps: MCP server and skills.

### macOS/Linux

Claude Code:
```bash
claude mcp add --transport stdio comsol-docs -- docs-mcp --db ~/.local/share/docs-mcp/comsol.db
mkdir -p ~/.claude/skills && curl -L https://raw.githubusercontent.com/jcdoll/htmlDocsRAG/main/.claude/skills/comsol-docs.md -o ~/.claude/skills/comsol-docs.md
```

Codex CLI: add to `~/.codex/config.toml`:
```toml
[mcp_servers.comsol-docs]
command = "docs-mcp"
args = ["--db", "comsol.db"]
```
```bash
mkdir -p ~/.codex/skills && curl -L https://raw.githubusercontent.com/jcdoll/htmlDocsRAG/main/.codex/skills/comsol-docs.md -o ~/.codex/skills/comsol-docs.md
```

Cursor: add to `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "comsol-docs": {
      "command": "docs-mcp",
      "args": ["--db", "~/.local/share/docs-mcp/comsol.db"]
    }
  }
}
```

### Windows

Claude Code (PowerShell):
```powershell
claude mcp add --transport stdio comsol-docs -- docs-mcp --db "$env:LOCALAPPDATA\docs-mcp\comsol.db"
mkdir -Force "$env:USERPROFILE\.claude\skills"; Invoke-WebRequest -Uri "https://raw.githubusercontent.com/jcdoll/htmlDocsRAG/main/.claude/skills/comsol-docs.md" -OutFile "$env:USERPROFILE\.claude\skills\comsol-docs.md"
```

Codex CLI: add to `%USERPROFILE%\.codex\config.toml`:
```toml
[mcp_servers.comsol-docs]
command = "docs-mcp"
args = ["--db", "comsol.db"]
```
```powershell
mkdir -Force "$env:USERPROFILE\.codex\skills"; Invoke-WebRequest -Uri "https://raw.githubusercontent.com/jcdoll/htmlDocsRAG/main/.codex/skills/comsol-docs.md" -OutFile "$env:USERPROFILE\.codex\skills\comsol-docs.md"
```

Cursor: add to `%USERPROFILE%\.cursor\mcp.json`:
```json
{
  "mcpServers": {
    "comsol-docs": {
      "command": "docs-mcp",
      "args": ["--db", "%LOCALAPPDATA%\\docs-mcp\\comsol.db"]
    }
  }
}
```

## Quick Start (Build Your Own)

```bash
git clone https://github.com/jcdoll/htmlDocsRAG.git && cd htmlDocsRAG
uv sync
./scripts/convert_html.sh /path/to/html/docs ./markdown
uv run python build_index.py ./markdown --output db/docs.db --no-embeddings
uv run python mcp_server.py --db db/docs.db --test "your query"
uv run python build_index.py ./markdown --output db/docs.db
uv tool install .
```

For COMSOL-specific conversion, see [docs/comsol.md](docs/comsol.md). You can adapt the approach for other HTML docs that have some nuance in the internal format.

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_docs` | Hybrid keyword + semantic search. Optional `source_filter` to narrow by path. |
| `get_stats` | Get database statistics (chunks, sources, modules, embeddings status). |
| `get_chunk` | Retrieve a specific chunk by ID. |
| `get_context` | Get a chunk with surrounding chunks from the same file for more context. |
| `get_source` | Get all chunks from a source file to read the full document. |
| `list_sources` | List all indexed source files with chunk counts. |
| `list_modules` | List modules/products with file counts for discovering available content. |
| `search_sources` | Search source paths by substring to find relevant files. |
| `list_sections` | List all section titles in a source file for quick navigation. |
| `get_chunk_by_title` | Get all chunks with a specific title from a source file. |
| `search_symbols` | Search for API/function symbols by prefix (e.g., "mph"). |
| `search_titles` | Search section titles across all sources (e.g., "API Reference"). |

Example `search_docs` response:
```json
[
  {
    "chunk_id": "comsol_ref_mesh.24.80.md:0",
    "source": "comsol_ref_mesh.24.80.md",
    "title": "Mesh Refinement",
    "content": "Use Refine to refine a mesh by splitting elements...",
    "score": 0.032
  }
]
```

## Publishing Databases

You can publish database snapshots for ease of use using the following example command:

```bash
gh release create 2025-12-21 db/comsol.db --title "Comsol 6.4 docs" --notes "Pre-built database with embeddings"
```

## Documentation

- [COMSOL-specific setup](docs/comsol.md)
- [Development guide](docs/development.md) - schema, chunking, build options
- [Troubleshooting](docs/troubleshooting.md)

## License

MIT
