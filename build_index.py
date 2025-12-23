#!/usr/bin/env python3
"""Build a searchable SQLite index from Markdown documentation."""

import argparse
import hashlib
import logging
import sqlite3
import sys
import time
from pathlib import Path

from chunking import process_file

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_embedding_model = None


def get_embedding_model(model_name: str):
    """Lazy-load the embedding model."""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(model_name)
    return _embedding_model


def file_hash(path: Path) -> str:
    """Compute SHA256 hash of file contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def init_database(db_path: Path, embedding_dim: int = 384) -> sqlite3.Connection:
    """Initialize database schema."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            path TEXT PRIMARY KEY,
            hash TEXT NOT NULL,
            indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            title, content, content=chunks, content_rowid=rowid,
            tokenize='porter unicode61'
        )
    """)

    # Triggers to keep FTS in sync
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, title, content)
            VALUES (NEW.rowid, NEW.title, NEW.content);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, title, content)
            VALUES ('delete', OLD.rowid, OLD.title, OLD.content);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, title, content)
            VALUES ('delete', OLD.rowid, OLD.title, OLD.content);
            INSERT INTO chunks_fts(rowid, title, content)
            VALUES (NEW.rowid, NEW.title, NEW.content);
        END
    """)

    # Vector index via sqlite-vec
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
                id TEXT PRIMARY KEY, embedding float[{embedding_dim}]
            )
        """)
    except Exception as e:
        logger.warning(f"sqlite-vec not available: {e}")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source)")
    conn.commit()
    return conn


def index_chunks(
    conn: sqlite3.Connection, chunks: list[dict], model_name: str | None, verbose: bool
) -> None:
    """Insert chunks into database with embeddings."""
    if not chunks:
        return

    conn.executemany(
        "INSERT OR REPLACE INTO chunks (id, source, title, content, chunk_index) "
        "VALUES (:id, :source, :title, :content, :chunk_index)",
        chunks,
    )

    if model_name:
        try:
            import struct

            model = get_embedding_model(model_name)
            texts = [c["content"] for c in chunks]
            logger.debug(f"Generating embeddings for {len(texts)} chunks...")
            embeddings = model.encode(texts, show_progress_bar=verbose)

            for chunk, embedding in zip(chunks, embeddings):
                blob = struct.pack(f"{len(embedding)}f", *embedding)
                conn.execute(
                    "INSERT OR REPLACE INTO chunks_vec (id, embedding) VALUES (?, ?)",
                    (chunk["id"], blob),
                )
        except Exception as e:
            logger.warning(f"Could not generate embeddings: {e}")

    conn.commit()


def main():
    parser = argparse.ArgumentParser(
        description="Build a searchable index from Markdown documentation."
    )
    parser.add_argument("source_dir", type=Path, help="Directory containing Markdown files")
    parser.add_argument(
        "--output", "-o", type=Path, default=Path("db/docs.db"), help="Output database path"
    )
    parser.add_argument(
        "--chunk-size", type=int, default=1500, help="Target chunk size in characters"
    )
    parser.add_argument("--chunk-overlap", type=int, default=200, help="Overlap between chunks")
    parser.add_argument(
        "--embedding-model", type=str, default="BAAI/bge-small-en-v1.5", help="Embedding model"
    )
    parser.add_argument("--no-embeddings", action="store_true", help="Skip embedding generation")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed progress")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.source_dir.is_dir():
        logger.error(f"{args.source_dir} is not a directory")
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)

    embedding_dim = 384
    model_name = None if args.no_embeddings else args.embedding_model

    if model_name:
        try:
            model = get_embedding_model(model_name)
            embedding_dim = model.get_sentence_embedding_dimension()
        except Exception as e:
            logger.warning(f"Could not load embedding model: {e}")
            logger.warning("Continuing without embeddings.")
            model_name = None

    conn = init_database(args.output, embedding_dim)

    md_files = list(args.source_dir.rglob("*.md"))
    total_files = len(md_files)
    logger.info(f"Found {total_files} Markdown files")

    total_chunks, files_processed, files_skipped = 0, 0, 0
    start_time = time.time()
    last_progress_time = start_time

    for i, md_path in enumerate(md_files):
        current_hash = file_hash(md_path)
        relative_path = str(md_path.relative_to(args.source_dir)).replace("\\", "/")

        existing = conn.execute(
            "SELECT hash FROM sources WHERE path = ?", (relative_path,)
        ).fetchone()
        if existing and existing[0] == current_hash:
            logger.debug(f"Skipping (unchanged): {relative_path}")
            files_skipped += 1
            continue

        logger.debug(f"Processing: {relative_path}")

        conn.execute("DELETE FROM chunks WHERE source = ?", (relative_path,))
        try:
            conn.execute("DELETE FROM chunks_vec WHERE id LIKE ?", (f"{relative_path}:%",))
        except sqlite3.OperationalError:
            pass

        chunks = process_file(md_path, args.source_dir, args.chunk_size, args.chunk_overlap)
        if chunks:
            index_chunks(conn, chunks, model_name, args.verbose)
            total_chunks += len(chunks)

        conn.execute(
            "INSERT OR REPLACE INTO sources (path, hash) VALUES (?, ?)",
            (relative_path, current_hash),
        )
        conn.commit()
        files_processed += 1

        # Progress reporting
        current_time = time.time()
        if current_time - last_progress_time >= 2 or (i + 1) % 100 == 0 or (i + 1) == total_files:
            elapsed = current_time - start_time
            completed = i + 1
            pct = (completed / total_files) * 100

            if files_processed > 0:
                avg_time = elapsed / files_processed
                remaining = total_files - completed
                ratio = files_processed / completed if completed > 0 else 1
                eta = remaining * ratio * avg_time
                eta_str = (
                    f"{eta / 3600:.1f}h"
                    if eta >= 3600
                    else f"{eta / 60:.1f}m"
                    if eta >= 60
                    else f"{eta:.0f}s"
                )
            else:
                eta_str = "calculating..."

            elapsed_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed / 60:.1f}m"
            logger.info(
                f"Progress: {completed}/{total_files} ({pct:.1f}%) | "
                f"Processed: {files_processed} | Skipped: {files_skipped} | "
                f"Elapsed: {elapsed_str} | ETA: {eta_str}"
            )
            last_progress_time = current_time

    total_time = time.time() - start_time
    time_str = (
        f"{total_time / 3600:.1f} hours"
        if total_time >= 3600
        else f"{total_time / 60:.1f} minutes"
        if total_time >= 60
        else f"{total_time:.0f} seconds"
    )

    logger.info(f"Done in {time_str}")
    logger.info(f"  Files processed: {files_processed}")
    logger.info(f"  Files skipped (unchanged): {files_skipped}")
    logger.info(f"  Total chunks indexed: {total_chunks}")
    logger.info(f"  Database: {args.output}")


if __name__ == "__main__":
    main()
