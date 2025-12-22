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
