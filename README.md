# Local Documentation Retrieval via MCP

Make engineering documentation searchable by LLM coding assistants (Claude Code, Cursor, Codex CLI). Uses SQLite FTS5 for keyword search and vector embeddings for semantic search. Single file, no external services.

## Requirements

- Python 3.11+
- uv (recommended) or pip
- ~500MB disk for typical docs corpus + embeddings

## Quick Start (Pre-built Database)

**macOS/Linux:**
```bash
uv tool install https://github.com/jcdoll/htmlDocsRAG.git
mkdir -p ~/.local/share/docs-mcp
curl -L https://github.com/jcdoll/htmlDocsRAG/releases/latest/download/comsol.db -o ~/.local/share/docs-mcp/comsol.db
docs-mcp --db comsol.db --test "mesh refinement"
```

**Windows (PowerShell):**
```powershell
uv tool install https://github.com/jcdoll/htmlDocsRAG.git
mkdir -Force "$env:LOCALAPPDATA\docs-mcp"
Invoke-WebRequest -Uri "https://github.com/jcdoll/htmlDocsRAG/releases/latest/download/comsol.db" -OutFile "$env:LOCALAPPDATA\docs-mcp\comsol.db"
docs-mcp --db comsol.db --test "mesh refinement"
```

**Configure your IDE:**
```bash
# Claude Code
claude mcp add --transport stdio comsol-docs -- docs-mcp --db comsol.db
mkdir -p ~/.claude/skills && curl -L https://raw.githubusercontent.com/jcdoll/htmlDocsRAG/main/.claude/skills/comsol-docs.md -o ~/.claude/skills/comsol-docs.md

# Codex CLI
codex mcp add comsol-docs "docs-mcp --db comsol.db"
mkdir -p ~/.codex/skills && curl -L https://raw.githubusercontent.com/jcdoll/htmlDocsRAG/main/.codex/skills/comsol-docs.md -o ~/.codex/skills/comsol-docs.md

# Cursor - add to ~/.cursor/mcp.json (see IDE Configuration below)
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

For COMSOL-specific conversion, see [docs/comsol.md](docs/comsol.md).

## IDE Configuration

**Cursor/Other IDEs** - add to `~/.cursor/mcp.json` (or equivalent):
```json
{
  "mcpServers": {
    "comsol-docs": {
      "command": "docs-mcp",
      "args": ["--db", "comsol.db"]
    }
  }
}
```

Database files in `~/.local/share/docs-mcp/` (Linux/macOS) or `%LOCALAPPDATA%\docs-mcp\` (Windows) can be referenced by name only.

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_docs` | Hybrid keyword + semantic search. Returns matching chunks with scores. |
| `get_chunk` | Retrieve a specific chunk by ID. |
| `list_sources` | List all indexed source files. |

## Publishing Databases

```bash
gh release create 2025-12-21 db/comsol.db --title "Comsol 6.4 docs" --notes "Pre-built database with embeddings"
```

## Documentation

- [COMSOL-specific setup](docs/comsol.md)
- [Development guide](docs/development.md) - schema, chunking, build options
- [Troubleshooting](docs/troubleshooting.md)

## License

MIT
