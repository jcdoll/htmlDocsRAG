# Troubleshooting

## "sqlite-vec extension not found"

sqlite-vec requires compilation on some platforms:

```bash
uv add sqlite-vec --reinstall

# If that fails on macOS
brew install sqlite
uv add sqlite-vec --reinstall
```

## "No results for queries that should match"

1. Check content was indexed:
   ```sql
   SELECT COUNT(*) FROM chunks WHERE content LIKE '%yourterm%'
   ```
2. FTS5 tokenization may differ from expectation. Try simpler queries.
3. For code symbols, ensure they weren't stripped during HTML→Markdown conversion.

## "MCP server not connecting"

1. Test manually:
   ```bash
   docs-mcp --db comsol.db --test "test query"
   ```
2. Check paths in IDE config are absolute
3. Restart IDE after changing MCP configuration
4. Check IDE's MCP debug logs

## Slow indexing

Embedding generation is the bottleneck (~5 min for 10k chunks). Options:

- Use `--no-embeddings` for initial testing, then rebuild with embeddings
- Use a smaller embedding model (trades accuracy for speed)
- Run on a machine with GPU (sentence-transformers auto-detects CUDA)

## Slow first search (hybrid/semantic mode)

The embedding model loads on first semantic search. This is a one-time cost per session. Use `--mode keyword` for fast CLI testing:

```bash
docs-mcp --db comsol.db --test "query" --mode keyword
```

## Windows-specific issues

### "Database is locked" or temp file errors

SQLite WAL mode can cause file locking issues on Windows. The server handles this automatically, but if you see errors:

1. Close any other programs accessing the database
2. Delete `.db-wal` and `.db-shm` files if present
3. Restart the MCP server

### NPX commands fail with "Connection closed"

On native Windows (not WSL), wrap NPX commands with `cmd /c`:

```powershell
# Instead of: npx -y some-package
cmd /c npx -y some-package
```

### Path issues

Always use forward slashes or escaped backslashes in config files:

```json
{
  "args": ["--db", "C:/Users/name/docs-mcp/comsol.db"]
}
```

Or use environment variables:

```json
{
  "args": ["--db", "comsol.db"]
}
```

(Database files in `%LOCALAPPDATA%\docs-mcp\` are found automatically.)
