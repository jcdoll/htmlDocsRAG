"""Pytest fixtures for local-docs-mcp tests."""

import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def cleanup_db():
    """Ensure database connection is closed after each test."""
    yield
    # Close any open database connection after each test
    from mcp_server import close_db

    close_db()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_markdown_files(temp_dir: Path) -> Path:
    """Create sample markdown files for testing."""
    docs_dir = temp_dir / "docs"
    docs_dir.mkdir()

    # Simple document
    (docs_dir / "simple.md").write_text("""# Simple Document

This is a simple document with one section.

It has multiple paragraphs to test chunking behavior.
""")

    # Document with multiple sections
    (docs_dir / "multi_section.md").write_text("""# Main Title

Introduction paragraph.

## First Section

Content of the first section. This section discusses important topics
that span multiple lines and contain various terms for searching.

### Subsection A

Detailed content in subsection A about mesh refinement and convergence.

### Subsection B

More content about boundary conditions and solver settings.

## Second Section

The second section covers different material entirely.
It mentions API functions like `compute_solution()` and `set_parameters()`.
""")

    # Document with code blocks
    (docs_dir / "with_code.md").write_text("""# API Reference

## Function: initialize

```python
def initialize(config: dict) -> None:
    \"\"\"Initialize the system with configuration.\"\"\"
    pass
```

### Parameters

- `config`: A dictionary containing configuration options.

### Example

```python
initialize({"mode": "fast", "threads": 4})
```
""")

    # Subdirectory
    subdir = docs_dir / "advanced"
    subdir.mkdir()
    (subdir / "topics.md").write_text("""# Advanced Topics

## Error Handling

When errors occur, check the following:

1. Verify input parameters
2. Check boundary conditions
3. Review mesh quality

## Performance Tuning

For optimal performance, consider mesh density and solver tolerance.
""")

    return docs_dir


@pytest.fixture
def temp_db(temp_dir: Path) -> Path:
    """Return path for a temporary database."""
    return temp_dir / "test.db"


@pytest.fixture
def populated_db(temp_db: Path, sample_markdown_files: Path) -> Path:
    """Create and populate a test database without embeddings."""
    from build_index import init_database, process_file

    conn = init_database(temp_db, embedding_dim=384)

    for md_path in sample_markdown_files.rglob("*.md"):
        chunks = process_file(
            md_path,
            sample_markdown_files,
            chunk_size=500,
            chunk_overlap=50,
        )
        if chunks:
            # Index without embeddings
            conn.executemany(
                """
                INSERT OR REPLACE INTO chunks (id, source, title, content, chunk_index)
                VALUES (:id, :source, :title, :content, :chunk_index)
            """,
                chunks,
            )
            conn.commit()

    conn.close()
    return temp_db
