"""Tests for the indexing pipeline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from build_index import file_hash, init_database
from chunking import process_file


class TestFileHash:
    """Tests for file hashing."""

    def test_consistent_hash(self, temp_dir: Path):
        test_file = temp_dir / "test.txt"
        test_file.write_text("consistent content")

        hash1 = file_hash(test_file)
        hash2 = file_hash(test_file)

        assert hash1 == hash2

    def test_different_content_different_hash(self, temp_dir: Path):
        file1 = temp_dir / "file1.txt"
        file2 = temp_dir / "file2.txt"

        file1.write_text("content one")
        file2.write_text("content two")

        assert file_hash(file1) != file_hash(file2)

    def test_hash_format(self, temp_dir: Path):
        test_file = temp_dir / "test.txt"
        test_file.write_text("test")

        h = file_hash(test_file)

        # SHA256 produces 64 hex characters
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestInitDatabase:
    """Tests for database initialization."""

    def test_creates_tables(self, temp_db: Path):
        conn = init_database(temp_db)

        # Check chunks table exists
        result = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'"
        ).fetchone()
        assert result is not None

        # Check sources table exists
        result = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sources'"
        ).fetchone()
        assert result is not None

        # Check FTS table exists
        result = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
        ).fetchone()
        assert result is not None

        conn.close()

    def test_idempotent(self, temp_db: Path):
        # Should be able to call multiple times without error
        conn1 = init_database(temp_db)
        conn1.close()

        conn2 = init_database(temp_db)
        conn2.close()

    def test_wal_mode_enabled(self, temp_db: Path):
        conn = init_database(temp_db)

        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0].lower() == "wal"

        conn.close()


class TestProcessFile:
    """Tests for file processing."""

    def test_basic_processing(self, sample_markdown_files: Path):
        simple_file = sample_markdown_files / "simple.md"
        chunks = process_file(
            simple_file,
            sample_markdown_files,
            chunk_size=1500,
            chunk_overlap=200,
        )

        assert len(chunks) >= 1
        assert all("id" in c for c in chunks)
        assert all("source" in c for c in chunks)
        assert all("content" in c for c in chunks)

    def test_source_path_relative(self, sample_markdown_files: Path):
        simple_file = sample_markdown_files / "simple.md"
        chunks = process_file(
            simple_file,
            sample_markdown_files,
            chunk_size=1500,
            chunk_overlap=200,
        )

        # Source should be relative path, not absolute
        assert chunks[0]["source"] == "simple.md"
        assert not chunks[0]["source"].startswith("/")

    def test_subdirectory_handling(self, sample_markdown_files: Path):
        subfile = sample_markdown_files / "advanced" / "topics.md"
        chunks = process_file(
            subfile,
            sample_markdown_files,
            chunk_size=1500,
            chunk_overlap=200,
        )

        assert chunks[0]["source"] == "advanced/topics.md"

    def test_chunk_ids_unique(self, sample_markdown_files: Path):
        multi_file = sample_markdown_files / "multi_section.md"
        chunks = process_file(
            multi_file,
            sample_markdown_files,
            chunk_size=200,  # Small to force multiple chunks
            chunk_overlap=20,
        )

        ids = [c["id"] for c in chunks]
        assert len(ids) == len(set(ids))  # All unique

    def test_titles_extracted(self, sample_markdown_files: Path):
        multi_file = sample_markdown_files / "multi_section.md"
        chunks = process_file(
            multi_file,
            sample_markdown_files,
            chunk_size=1500,
            chunk_overlap=200,
        )

        titles = [c["title"] for c in chunks if c["title"]]
        assert len(titles) >= 1

    def test_chunk_index_sequential(self, sample_markdown_files: Path):
        multi_file = sample_markdown_files / "multi_section.md"
        chunks = process_file(
            multi_file,
            sample_markdown_files,
            chunk_size=200,
            chunk_overlap=20,
        )

        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))


class TestFTSTriggers:
    """Tests for FTS synchronization triggers."""

    def test_insert_syncs_to_fts(self, temp_db: Path):
        conn = init_database(temp_db)

        conn.execute("""
            INSERT INTO chunks (id, source, title, content, chunk_index)
            VALUES ('test:0', 'test.md', 'Test Title', 'searchable content here', 0)
        """)
        conn.commit()

        # Search should find it
        result = conn.execute("""
            SELECT c.id FROM chunks_fts
            JOIN chunks c ON chunks_fts.rowid = c.rowid
            WHERE chunks_fts MATCH 'searchable'
        """).fetchone()

        assert result is not None
        assert result[0] == "test:0"

        conn.close()

    def test_delete_syncs_to_fts(self, temp_db: Path):
        conn = init_database(temp_db)

        conn.execute("""
            INSERT INTO chunks (id, source, title, content, chunk_index)
            VALUES ('test:0', 'test.md', 'Test', 'unique_term_xyz', 0)
        """)
        conn.commit()

        # Verify it's searchable
        assert (
            conn.execute(
                "SELECT * FROM chunks_fts WHERE chunks_fts MATCH 'unique_term_xyz'"
            ).fetchone()
            is not None
        )

        # Delete it
        conn.execute("DELETE FROM chunks WHERE id = 'test:0'")
        conn.commit()

        # Should no longer be searchable
        result = conn.execute(
            "SELECT * FROM chunks_fts WHERE chunks_fts MATCH 'unique_term_xyz'"
        ).fetchone()
        assert result is None

        conn.close()

    def test_update_syncs_to_fts(self, temp_db: Path):
        conn = init_database(temp_db)

        conn.execute("""
            INSERT INTO chunks (id, source, title, content, chunk_index)
            VALUES ('test:0', 'test.md', 'Test', 'original_content_abc', 0)
        """)
        conn.commit()

        # Update content
        conn.execute("""
            UPDATE chunks SET content = 'updated_content_xyz' WHERE id = 'test:0'
        """)
        conn.commit()

        # Old content should not be found
        assert (
            conn.execute(
                "SELECT * FROM chunks_fts WHERE chunks_fts MATCH 'original_content_abc'"
            ).fetchone()
            is None
        )

        # New content should be found
        assert (
            conn.execute(
                "SELECT * FROM chunks_fts WHERE chunks_fts MATCH 'updated_content_xyz'"
            ).fetchone()
            is not None
        )

        conn.close()
