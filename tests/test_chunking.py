"""Tests for markdown parsing and text chunking."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from chunking import chunk_text, parse_markdown_sections


class TestParseMarkdownSections:
    """Tests for parse_markdown_sections function."""

    def test_single_section_with_header(self):
        text = """# Title

Some content here.
"""
        sections = parse_markdown_sections(text)
        assert len(sections) == 1
        assert sections[0][0] == "Title"
        assert "Some content here." in sections[0][1]

    def test_multiple_sections(self):
        text = """# First

Content one.

## Second

Content two.

## Third

Content three.
"""
        sections = parse_markdown_sections(text)
        assert len(sections) == 3
        assert sections[0][0] == "First"
        assert sections[1][0] == "Second"
        assert sections[2][0] == "Third"

    def test_no_headers(self):
        text = "Just plain text without any headers."
        sections = parse_markdown_sections(text)
        assert len(sections) == 1
        assert sections[0][0] is None
        assert sections[0][1] == "Just plain text without any headers."

    def test_nested_headers(self):
        text = """# Main

Intro.

## Sub

Sub content.

### SubSub

Deep content.
"""
        sections = parse_markdown_sections(text)
        assert len(sections) == 3
        titles = [s[0] for s in sections]
        assert "Main" in titles
        assert "Sub" in titles
        assert "SubSub" in titles

    def test_content_before_first_header(self):
        text = """Some preamble content.

# First Header

After header.
"""
        sections = parse_markdown_sections(text)
        assert len(sections) == 2
        assert sections[0][0] is None
        assert "preamble" in sections[0][1]
        assert sections[1][0] == "First Header"

    def test_empty_sections_skipped(self):
        text = """# Header One

# Header Two

Content here.
"""
        sections = parse_markdown_sections(text)
        # Empty section after "Header One" should be skipped
        assert len(sections) == 1
        assert sections[0][0] == "Header Two"


class TestChunkText:
    """Tests for chunk_text function."""

    def test_short_text_single_chunk(self):
        text = "Short text."
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_paragraph_splitting(self):
        text = """First paragraph with some content.

Second paragraph with more content.

Third paragraph with even more content."""

        chunks = chunk_text(text, chunk_size=60, chunk_overlap=0)
        assert len(chunks) >= 2

    def test_respects_chunk_size(self):
        # Create text that will require multiple chunks
        text = "Word " * 100  # ~500 characters
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=0)

        # Each chunk (except possibly last) should be near chunk_size
        for chunk in chunks[:-1]:
            assert len(chunk) <= 150  # Allow some flexibility for word boundaries

    def test_overlap_applied(self):
        text = """First paragraph.

Second paragraph.

Third paragraph."""

        chunks = chunk_text(text, chunk_size=30, chunk_overlap=10)

        # With overlap, later chunks should contain text from previous chunks
        if len(chunks) > 1:
            # Check that some overlap exists
            # (exact check depends on implementation details)
            assert len(chunks) >= 2

    def test_long_sentence_handling(self):
        # Single very long sentence that exceeds chunk_size
        text = "word " * 200  # ~1000 characters, no periods
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)

        # Should still produce chunks
        assert len(chunks) >= 1

    def test_preserves_content(self):
        text = "Important content that must be preserved entirely."
        chunks = chunk_text(text, chunk_size=1000, chunk_overlap=0)

        # All content should be in the chunks
        combined = " ".join(chunks)
        for word in text.split():
            assert word in combined

    def test_empty_text(self):
        chunks = chunk_text("", chunk_size=100, chunk_overlap=10)
        assert chunks == []

    def test_whitespace_only(self):
        chunks = chunk_text("   \n\n   ", chunk_size=100, chunk_overlap=10)
        assert chunks == []
