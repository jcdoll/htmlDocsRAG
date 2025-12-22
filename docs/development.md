# Development Guide

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

## Search Modes

### Hybrid (default)

Combines FTS5 keyword matching with vector similarity using Reciprocal Rank Fusion (RRF):

```
score = Σ 1/(k + rank_i)
```

Where `k=60` (standard RRF constant) and `rank_i` is the rank from each method.

### Keyword-Only

Uses SQLite FTS5 with BM25 ranking. Best for exact terms, API names, error messages.

### Semantic-Only

Uses cosine similarity on embeddings. Handles vocabulary mismatch ("make grid finer" → "mesh refinement").

## Build Options

```
--output PATH       Output database path (default: db/docs.db)
--chunk-size N      Target chunk size in characters (default: 1500)
--chunk-overlap N   Overlap between chunks (default: 200)
--embedding-model   Model name (default: BAAI/bge-small-en-v1.5)
--no-embeddings     Skip embedding generation (testing only)
--verbose           Show progress details
```

## Maintenance

### Updating Documentation

```bash
./scripts/convert_html.sh /path/to/html ./markdown
uv run python build_index.py ./markdown --output db/docs.db
```

The script hashes files and skips unchanged content.

### Validation

```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('db/docs.db')
print(f'Chunks: {conn.execute(\"SELECT COUNT(*) FROM chunks\").fetchone()[0]}')
print(f'Sources: {conn.execute(\"SELECT COUNT(*) FROM sources\").fetchone()[0]}')
"
```

## HTML Conversion

For documentation with semantic HTML (`<h1>`, `<h2>`, `<p>` tags):

```bash
./scripts/convert_html.sh /path/to/html/docs ./markdown
```

For other formats:

```bash
pandoc -f rst -t gfm input.rst -o output.md   # Sphinx RST
pandoc -f docx -t gfm input.docx -o output.md # Word docs
```

## Running Tests

```bash
uv run pytest tests/ -v
```

Tests cover chunking, indexing, FTS triggers, RRF scoring, and search functionality. All tests use temporary databases and clean up after themselves.

## Creating Skills for New Documentation

Skills help LLMs know when to use your MCP server. Create a skill file for each documentation set.

### Skill Format

Both Claude Code and Codex use the [Agent Skills specification](https://agentskills.io/specification):

```markdown
---
name: your-docs
description: Search YOUR_PRODUCT documentation. Use when asked about [list key topics, features, common questions].
---

# Your Documentation Search

Use the `search_docs` MCP tool to find documentation.

## When to use

- [List specific use cases]
- [Topics this documentation covers]
- [Types of questions it answers]

## Prerequisites

The MCP server must be configured:
\`\`\`bash
claude mcp add --transport stdio your-docs -- docs-mcp --db your-docs.db
\`\`\`
```

### Skill Locations

| IDE | User-level location |
|-----|---------------------|
| Claude Code | `~/.claude/skills/your-docs.md` |
| Codex CLI | `~/.codex/skills/your-docs.md` |

### Tips

- Be specific in the description - include keywords users would mention
- List concrete examples - helps the LLM match user queries to your skill
- Update prerequisites - use the correct MCP add command for each IDE

## Embedding Models

The default model is `BAAI/bge-small-en-v1.5`. You can change it with `--embedding-model`.

| Model | Dimensions | Size | Speed | Quality | Notes |
|-------|------------|------|-------|---------|-------|
| `BAAI/bge-small-en-v1.5` | 384 | 130MB | Fast | Good | Default, best balance |
| `BAAI/bge-base-en-v1.5` | 768 | 440MB | Medium | Better | More accurate, 2x slower |
| `BAAI/bge-large-en-v1.5` | 1024 | 1.3GB | Slow | Best | Diminishing returns for docs |
| `all-MiniLM-L6-v2` | 384 | 90MB | Fastest | OK | Smaller, less accurate |

### Recommendations

- bge-small (default): Best for most use cases. Good accuracy, fast indexing.
- bge-base: Use if search quality matters more than indexing time.
- bge-large: Rarely needed. The accuracy gain over base is marginal for documentation.
- MiniLM: Use if disk space or memory is constrained.

### GPU Acceleration

sentence-transformers auto-detects CUDA. On a GPU, even bge-large indexes quickly.

```bash
# Check if GPU is available
python -c "import torch; print(torch.cuda.is_available())"
```

## Performance Tuning

### Chunk Size

| Setting | Effect |
|---------|--------|
| Smaller chunks (500-1000) | More precise matches, more chunks to search, larger database |
| Larger chunks (2000-3000) | More context per result, fewer chunks, may include irrelevant content |
| Default (1500) | Good balance for technical documentation |

### Chunk Overlap

| Setting | Effect |
|---------|--------|
| No overlap (0) | Smallest database, may miss matches at chunk boundaries |
| Small overlap (100-200) | Default, catches most boundary cases |
| Large overlap (300+) | Better boundary matching, larger database, more redundancy |

### When to Use Each Search Mode

| Mode | Best for | Speed |
|------|----------|-------|
| `keyword` | Exact terms, API names, error codes, CLI testing | Instant |
| `semantic` | Natural language, vocabulary mismatch, conceptual queries | Slower (model load) |
| `hybrid` | Production use, best overall results | Slower (model load) |

### Indexing Performance

- Without embeddings: ~1000 files/second
- With embeddings (CPU): ~50 chunks/second
- With embeddings (GPU): ~500 chunks/second

For large documentation sets (10k+ files), use `--no-embeddings` first to verify conversion worked, then rebuild with embeddings.
