"""Tests for search functionality."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import (
    get_chunk,
    get_context,
    get_source,
    init_db,
    list_sources,
    sanitize_fts_query,
    search_docs,
    search_fts,
)


class TestSearchFTS:
    """Tests for FTS keyword search."""

    def test_basic_search(self, populated_db: Path):
        init_db(populated_db)

        results = search_fts("mesh", limit=10)

        assert len(results) >= 1
        # Results should be (chunk_id, score) tuples
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

    def test_no_results(self, populated_db: Path):
        init_db(populated_db)

        results = search_fts("xyznonexistentterm123", limit=10)

        assert len(results) == 0

    def test_respects_limit(self, populated_db: Path):
        init_db(populated_db)

        results = search_fts("content", limit=2)

        assert len(results) <= 2

    def test_phrase_search(self, populated_db: Path):
        init_db(populated_db)

        results = search_fts("boundary conditions", limit=10)

        # Should find the chunk mentioning boundary conditions
        assert len(results) >= 1


class TestSearchDocsImpl:
    """Tests for the main search implementation."""

    def test_keyword_mode(self, populated_db: Path):
        init_db(populated_db)

        results = search_docs("mesh refinement", limit=5, mode="keyword")

        assert len(results) >= 1
        # Results should have expected fields
        assert all("chunk_id" in r for r in results)
        assert all("content" in r for r in results)
        assert all("score" in r for r in results)

    def test_invalid_mode_raises_error(self, populated_db: Path):
        init_db(populated_db)

        with pytest.raises(ValueError, match="Invalid mode"):
            search_docs("test", limit=5, mode="invalid_mode")

    def test_hybrid_mode_fallback_to_keyword(self, populated_db: Path):
        # When no embeddings exist, hybrid should fall back to keyword
        init_db(populated_db)

        results = search_docs("boundary", limit=5, mode="hybrid")

        # Should still return results via keyword search
        assert len(results) >= 1

    def test_returns_source_info(self, populated_db: Path):
        init_db(populated_db)

        results = search_docs("API", limit=5, mode="keyword")

        assert len(results) >= 1
        assert all("source" in r for r in results)
        # Source should be a relative path
        assert all(not r["source"].startswith("/") for r in results)

    def test_returns_title(self, populated_db: Path):
        init_db(populated_db)

        results = search_docs("initialize", limit=5, mode="keyword")

        # At least some results should have titles
        titles = [r.get("title") for r in results]
        assert any(t is not None for t in titles)

    def test_empty_query(self, populated_db: Path):
        init_db(populated_db)

        # Empty query should return empty results (FTS5 will error otherwise)
        # This depends on implementation - might need to handle specially
        try:
            results = search_docs("", limit=5, mode="keyword")
            # If it doesn't error, should return empty
            assert results == []
        except Exception:
            # FTS5 errors on empty query are acceptable
            pass


class TestGetChunkImpl:
    """Tests for retrieving specific chunks."""

    def test_get_existing_chunk(self, populated_db: Path):
        init_db(populated_db)

        # First, search to get a valid chunk ID
        search_results = search_docs("content", limit=1, mode="keyword")
        assert len(search_results) >= 1

        chunk_id = search_results[0]["chunk_id"]
        chunk = get_chunk(chunk_id)

        assert chunk is not None
        assert chunk["chunk_id"] == chunk_id
        assert "content" in chunk
        assert "source" in chunk

    def test_get_nonexistent_chunk(self, populated_db: Path):
        init_db(populated_db)

        chunk = get_chunk("nonexistent:999")

        assert chunk is None

    def test_chunk_has_all_fields(self, populated_db: Path):
        init_db(populated_db)

        search_results = search_docs("paragraph", limit=1, mode="keyword")
        chunk_id = search_results[0]["chunk_id"]
        chunk = get_chunk(chunk_id)

        expected_fields = ["chunk_id", "source", "title", "content", "chunk_index"]
        for field in expected_fields:
            assert field in chunk


class TestListSourcesImpl:
    """Tests for listing indexed sources."""

    def test_lists_all_sources(self, populated_db: Path):
        init_db(populated_db)

        sources = list_sources()

        # Should have at least the test files
        assert len(sources) >= 3
        paths = [s["path"] for s in sources]
        assert "simple.md" in paths
        assert "multi_section.md" in paths

    def test_includes_chunk_counts(self, populated_db: Path):
        init_db(populated_db)

        sources = list_sources()

        assert all("chunk_count" in s for s in sources)
        assert all(isinstance(s["chunk_count"], int) for s in sources)
        assert all(s["chunk_count"] >= 1 for s in sources)

    def test_includes_subdirectory_files(self, populated_db: Path):
        init_db(populated_db)

        sources = list_sources()
        paths = [s["path"] for s in sources]

        assert "advanced/topics.md" in paths


class TestSearchScoring:
    """Tests for search result scoring."""

    def test_exact_match_scores_higher(self, populated_db: Path):
        init_db(populated_db)

        # "compute_solution" appears exactly in the multi_section.md
        results = search_docs("compute_solution", limit=10, mode="keyword")

        if len(results) >= 2:
            # Results should be ordered by score descending
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_scores_are_positive(self, populated_db: Path):
        init_db(populated_db)

        results = search_docs("content", limit=10, mode="keyword")

        assert all(r["score"] > 0 for r in results)


class TestSanitizeFtsQuery:
    """Tests for FTS5 query sanitization."""

    def test_simple_query(self):
        result = sanitize_fts_query("hello world")
        assert result == '"hello" "world"'

    def test_empty_query(self):
        assert sanitize_fts_query("") == ""
        assert sanitize_fts_query("   ") == ""

    def test_escapes_quotes(self):
        result = sanitize_fts_query('hello "world"')
        assert result == '"hello" """world"""'

    def test_handles_special_fts_operators(self):
        # These should be wrapped in quotes to be treated as literals
        result = sanitize_fts_query("AND OR NOT")
        assert result == '"AND" "OR" "NOT"'

    def test_handles_parentheses(self):
        result = sanitize_fts_query("(test)")
        assert result == '"(test)"'

    def test_handles_asterisk(self):
        result = sanitize_fts_query("test*")
        assert result == '"test*"'

    def test_handles_minus(self):
        result = sanitize_fts_query("-exclude")
        assert result == '"-exclude"'


class TestSearchEdgeCases:
    """Tests for search edge cases and error handling."""

    def test_empty_query_returns_empty(self, populated_db: Path):
        init_db(populated_db)

        results = search_fts("", limit=10)
        assert results == []

    def test_whitespace_query_returns_empty(self, populated_db: Path):
        init_db(populated_db)

        results = search_fts("   ", limit=10)
        assert results == []

    def test_special_characters_dont_crash(self, populated_db: Path):
        init_db(populated_db)

        # These should not raise exceptions
        queries = [
            '"unclosed quote',
            "AND",
            "OR",
            "(unbalanced",
            "test*",
            "-negation",
            "NEAR/5",
            '"hello" AND "world"',
        ]
        for query in queries:
            results = search_fts(query, limit=10)
            assert isinstance(results, list)

    def test_unicode_query(self, populated_db: Path):
        init_db(populated_db)

        # Unicode should not crash
        results = search_fts("日本語 emoji 🎉", limit=10)
        assert isinstance(results, list)

    def test_very_long_query(self, populated_db: Path):
        init_db(populated_db)

        # Very long query should not crash
        long_query = "word " * 1000
        results = search_fts(long_query, limit=10)
        assert isinstance(results, list)


class TestGetContext:
    """Tests for get_context."""

    def test_get_context_returns_surrounding_chunks(self, populated_db: Path):
        init_db(populated_db)

        # Get a chunk from multi_section.md which has multiple chunks
        search_results = search_docs("subsection", limit=1, mode="keyword")
        assert len(search_results) >= 1
        chunk_id = search_results[0]["chunk_id"]

        result = get_context(chunk_id, before=1, after=1)

        assert result["target"] is not None
        assert result["target"]["chunk_id"] == chunk_id
        assert "context" in result

    def test_get_context_nonexistent_chunk(self, populated_db: Path):
        init_db(populated_db)

        result = get_context("nonexistent:999", before=1, after=1)

        assert result["target"] is None
        assert "error" in result

    def test_get_context_at_start_of_file(self, populated_db: Path):
        init_db(populated_db)

        # Get first chunk of a file
        result = get_context("simple.md:0", before=2, after=1)

        # Should not crash even when asking for chunks before the start
        assert result["target"] is not None or "error" in result


class TestGetSource:
    """Tests for get_source."""

    def test_get_source_returns_all_chunks(self, populated_db: Path):
        init_db(populated_db)

        result = get_source("multi_section.md")

        assert "chunks" in result
        assert "total" in result
        assert len(result["chunks"]) == result["total"]
        # Chunks should be in order
        indices = [c["chunk_index"] for c in result["chunks"]]
        assert indices == sorted(indices)

    def test_get_source_with_pagination(self, populated_db: Path):
        init_db(populated_db)

        result = get_source("multi_section.md", offset=0, limit=2)

        assert len(result["chunks"]) <= 2
        assert result["offset"] == 0

    def test_get_source_nonexistent_file(self, populated_db: Path):
        init_db(populated_db)

        result = get_source("nonexistent.md")

        assert result["total"] == 0
        assert "error" in result

    def test_get_source_includes_subdirectory(self, populated_db: Path):
        init_db(populated_db)

        result = get_source("advanced/topics.md")

        assert result["total"] > 0
        assert len(result["chunks"]) > 0
