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

1. **Primary split:** Markdown headers (`##`, `###`, etc.)
2. **Secondary split:** If a section exceeds `chunk_size`, split on paragraph boundaries
3. **Tertiary split:** If still too large, split on sentence boundaries
4. **Overlap:** Each chunk includes `chunk_overlap` characters from the previous chunk's end

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
