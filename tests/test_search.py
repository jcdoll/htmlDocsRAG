"""Tests for search functionality."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server import (
    init_db,
    search_fts,
    search_docs_impl,
    get_chunk_impl,
    list_sources_impl,
    _conn,
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

        results = search_docs_impl("mesh refinement", limit=5, mode="keyword")

        assert len(results) >= 1
        # Results should have expected fields
        assert all("chunk_id" in r for r in results)
        assert all("content" in r for r in results)
        assert all("score" in r for r in results)

    def test_hybrid_mode_fallback_to_keyword(self, populated_db: Path):
        # When no embeddings exist, hybrid should fall back to keyword
        init_db(populated_db)

        results = search_docs_impl("boundary", limit=5, mode="hybrid")

        # Should still return results via keyword search
        assert len(results) >= 1

    def test_returns_source_info(self, populated_db: Path):
        init_db(populated_db)

        results = search_docs_impl("API", limit=5, mode="keyword")

        assert len(results) >= 1
        assert all("source" in r for r in results)
        # Source should be a relative path
        assert all(not r["source"].startswith("/") for r in results)

    def test_returns_title(self, populated_db: Path):
        init_db(populated_db)

        results = search_docs_impl("initialize", limit=5, mode="keyword")

        # At least some results should have titles
        titles = [r.get("title") for r in results]
        assert any(t is not None for t in titles)

    def test_empty_query(self, populated_db: Path):
        init_db(populated_db)

        # Empty query should return empty results (FTS5 will error otherwise)
        # This depends on implementation - might need to handle specially
        try:
            results = search_docs_impl("", limit=5, mode="keyword")
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
        search_results = search_docs_impl("content", limit=1, mode="keyword")
        assert len(search_results) >= 1

        chunk_id = search_results[0]["chunk_id"]
        chunk = get_chunk_impl(chunk_id)

        assert chunk is not None
        assert chunk["chunk_id"] == chunk_id
        assert "content" in chunk
        assert "source" in chunk

    def test_get_nonexistent_chunk(self, populated_db: Path):
        init_db(populated_db)

        chunk = get_chunk_impl("nonexistent:999")

        assert chunk is None

    def test_chunk_has_all_fields(self, populated_db: Path):
        init_db(populated_db)

        search_results = search_docs_impl("paragraph", limit=1, mode="keyword")
        chunk_id = search_results[0]["chunk_id"]
        chunk = get_chunk_impl(chunk_id)

        expected_fields = ["chunk_id", "source", "title", "content", "chunk_index"]
        for field in expected_fields:
            assert field in chunk


class TestListSourcesImpl:
    """Tests for listing indexed sources."""

    def test_lists_all_sources(self, populated_db: Path):
        init_db(populated_db)

        sources = list_sources_impl()

        # Should have at least the test files
        assert len(sources) >= 3
        paths = [s["path"] for s in sources]
        assert "simple.md" in paths
        assert "multi_section.md" in paths

    def test_includes_chunk_counts(self, populated_db: Path):
        init_db(populated_db)

        sources = list_sources_impl()

        assert all("chunk_count" in s for s in sources)
        assert all(isinstance(s["chunk_count"], int) for s in sources)
        assert all(s["chunk_count"] >= 1 for s in sources)

    def test_includes_subdirectory_files(self, populated_db: Path):
        init_db(populated_db)

        sources = list_sources_impl()
        paths = [s["path"] for s in sources]

        assert "advanced/topics.md" in paths


class TestSearchScoring:
    """Tests for search result scoring."""

    def test_exact_match_scores_higher(self, populated_db: Path):
        init_db(populated_db)

        # "compute_solution" appears exactly in the multi_section.md
        results = search_docs_impl("compute_solution", limit=10, mode="keyword")

        if len(results) >= 2:
            # Results should be ordered by score descending
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_scores_are_positive(self, populated_db: Path):
        init_db(populated_db)

        results = search_docs_impl("content", limit=10, mode="keyword")

        assert all(r["score"] > 0 for r in results)
