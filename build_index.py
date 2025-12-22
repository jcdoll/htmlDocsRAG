#!/usr/bin/env python3
"""
Build a searchable SQLite index from Markdown documentation.

Creates:
- FTS5 index for keyword search
- Vector embeddings for semantic search (via sqlite-vec)
- Source tracking for incremental updates
"""

import argparse
import hashlib
import re
import sqlite3
import sys
import time
from pathlib import Path

# Lazy imports for optional heavy dependencies
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
    
    # Main chunks table
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
    
    # Source tracking for incremental updates
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            path TEXT PRIMARY KEY,
            hash TEXT NOT NULL,
            indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # FTS5 full-text index
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            title,
            content,
            content=chunks,
            content_rowid=rowid,
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
                id TEXT PRIMARY KEY,
                embedding float[{embedding_dim}]
            )
        """)
    except Exception as e:
        print(f"Warning: sqlite-vec not available ({e}). Semantic search disabled.", file=sys.stderr)
    
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source)")
    conn.commit()
    return conn


def parse_markdown_sections(text: str) -> list[tuple[str | None, str]]:
    """
    Split markdown into sections based on headers.
    Returns list of (title, content) tuples.
    """
    # Match markdown headers (## Header or ### Header, etc.)
    header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    
    sections = []
    last_end = 0
    last_title = None
    
    for match in header_pattern.finditer(text):
        # Content before this header belongs to previous section
        if match.start() > last_end:
            content = text[last_end:match.start()].strip()
            if content:
                sections.append((last_title, content))
        
        last_title = match.group(2).strip()
        last_end = match.end()
    
    # Don't forget content after the last header
    if last_end < len(text):
        content = text[last_end:].strip()
        if content:
            sections.append((last_title, content))
    
    # Handle case with no headers
    if not sections and text.strip():
        sections.append((None, text.strip()))
    
    return sections


def chunk_text(
    text: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[str]:
    """
    Split text into chunks respecting paragraph and sentence boundaries.
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    
    # Try splitting on double newlines (paragraphs)
    paragraphs = re.split(r'\n\n+', text)
    
    current_chunk = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk = f"{current_chunk}\n\n{para}" if current_chunk else para
        else:
            if current_chunk:
                chunks.append(current_chunk)
            
            # If single paragraph exceeds chunk size, split on sentences
            if len(para) > chunk_size:
                sentences = re.split(r'(?<=[.!?])\s+', para)
                current_chunk = ""
                for sent in sentences:
                    if len(current_chunk) + len(sent) + 1 <= chunk_size:
                        current_chunk = f"{current_chunk} {sent}" if current_chunk else sent
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        # If single sentence exceeds chunk size, hard split
                        if len(sent) > chunk_size:
                            for i in range(0, len(sent), chunk_size - chunk_overlap):
                                chunks.append(sent[i:i + chunk_size])
                            current_chunk = ""
                        else:
                            current_chunk = sent
            else:
                current_chunk = para
    
    if current_chunk:
        chunks.append(current_chunk)
    
    # Add overlap
    if chunk_overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_end = chunks[i-1][-chunk_overlap:] if len(chunks[i-1]) > chunk_overlap else chunks[i-1]
            overlapped.append(prev_end + " " + chunks[i])
        chunks = overlapped
    
    return chunks


def process_file(
    path: Path,
    base_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict]:
    """Process a single markdown file into chunks."""
    text = path.read_text(encoding='utf-8', errors='replace')
    relative_path = str(path.relative_to(base_dir))
    
    sections = parse_markdown_sections(text)
    
    all_chunks = []
    chunk_index = 0
    
    for title, content in sections:
        text_chunks = chunk_text(content, chunk_size, chunk_overlap)
        
        for chunk_text_content in text_chunks:
            chunk_id = f"{relative_path}:{chunk_index}"
            all_chunks.append({
                'id': chunk_id,
                'source': relative_path,
                'title': title,
                'content': chunk_text_content,
                'chunk_index': chunk_index,
            })
            chunk_index += 1
    
    return all_chunks


def index_chunks(
    conn: sqlite3.Connection,
    chunks: list[dict],
    model_name: str | None,
    verbose: bool,
) -> None:
    """Insert chunks into database with embeddings."""
    if not chunks:
        return
    
    # Insert chunk metadata and content
    conn.executemany("""
        INSERT OR REPLACE INTO chunks (id, source, title, content, chunk_index)
        VALUES (:id, :source, :title, :content, :chunk_index)
    """, chunks)
    
    # Generate and insert embeddings
    if model_name:
        try:
            model = get_embedding_model(model_name)
            texts = [c['content'] for c in chunks]
            
            if verbose:
                print(f"  Generating embeddings for {len(texts)} chunks...")
            
            embeddings = model.encode(texts, show_progress_bar=verbose)
            
            # sqlite-vec expects the embedding as a blob
            import struct
            for chunk, embedding in zip(chunks, embeddings):
                embedding_blob = struct.pack(f'{len(embedding)}f', *embedding)
                conn.execute("""
                    INSERT OR REPLACE INTO chunks_vec (id, embedding)
                    VALUES (?, ?)
                """, (chunk['id'], embedding_blob))
        except Exception as e:
            print(f"Warning: Could not generate embeddings: {e}", file=sys.stderr)
    
    conn.commit()


def main():
    parser = argparse.ArgumentParser(
        description="Build a searchable index from Markdown documentation."
    )
    parser.add_argument(
        "source_dir",
        type=Path,
        help="Directory containing Markdown files",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("db/docs.db"),
        help="Output database path (default: db/docs.db)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1500,
        help="Target chunk size in characters (default: 1500)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=200,
        help="Overlap between chunks in characters (default: 200)",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default="BAAI/bge-small-en-v1.5",
        help="Sentence transformer model (default: BAAI/bge-small-en-v1.5)",
    )
    parser.add_argument(
        "--no-embeddings",
        action="store_true",
        help="Skip embedding generation (FTS5 only)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed progress",
    )
    
    args = parser.parse_args()
    
    if not args.source_dir.is_dir():
        print(f"Error: {args.source_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Ensure output directory exists
    args.output.parent.mkdir(parents=True, exist_ok=True)
    
    # Get embedding dimension from model (or default)
    embedding_dim = 384  # Default for bge-small
    model_name = None if args.no_embeddings else args.embedding_model
    
    if model_name and not args.no_embeddings:
        try:
            model = get_embedding_model(model_name)
            embedding_dim = model.get_sentence_embedding_dimension()
        except Exception as e:
            print(f"Warning: Could not load embedding model: {e}", file=sys.stderr)
            print("Continuing without embeddings.", file=sys.stderr)
            model_name = None
    
    # Initialize database
    conn = init_database(args.output, embedding_dim)
    
    # Find all markdown files
    md_files = list(args.source_dir.rglob("*.md"))
    total_files = len(md_files)
    print(f"Found {total_files} Markdown files")

    # Process each file
    total_chunks = 0
    files_processed = 0
    files_skipped = 0
    start_time = time.time()
    last_progress_time = start_time

    for i, md_path in enumerate(md_files):
        # Check if file has changed
        current_hash = file_hash(md_path)
        relative_path = str(md_path.relative_to(args.source_dir))

        existing = conn.execute(
            "SELECT hash FROM sources WHERE path = ?",
            (relative_path,)
        ).fetchone()

        if existing and existing[0] == current_hash:
            if args.verbose:
                print(f"  Skipping (unchanged): {relative_path}")
            files_skipped += 1
            continue

        if args.verbose:
            print(f"  Processing: {relative_path}")

        # Remove old chunks for this source
        conn.execute("DELETE FROM chunks WHERE source = ?", (relative_path,))
        try:
            conn.execute("DELETE FROM chunks_vec WHERE id LIKE ?", (f"{relative_path}:%",))
        except sqlite3.OperationalError:
            pass  # chunks_vec might not exist

        # Process and index
        chunks = process_file(
            md_path,
            args.source_dir,
            args.chunk_size,
            args.chunk_overlap,
        )

        if chunks:
            index_chunks(conn, chunks, model_name, args.verbose)
            total_chunks += len(chunks)

        # Update source tracking
        conn.execute("""
            INSERT OR REPLACE INTO sources (path, hash) VALUES (?, ?)
        """, (relative_path, current_hash))
        conn.commit()

        files_processed += 1

        # Progress update every 2 seconds or every 100 files
        current_time = time.time()
        if current_time - last_progress_time >= 2 or (i + 1) % 100 == 0 or (i + 1) == total_files:
            elapsed = current_time - start_time
            completed = i + 1
            pct = (completed / total_files) * 100

            # Calculate ETA based on files processed (not skipped)
            if files_processed > 0:
                avg_time_per_file = elapsed / files_processed
                remaining_to_process = total_files - completed
                # Estimate how many of remaining will need processing (use current ratio)
                process_ratio = files_processed / completed if completed > 0 else 1
                eta_seconds = remaining_to_process * process_ratio * avg_time_per_file

                if eta_seconds >= 3600:
                    eta_str = f"{eta_seconds / 3600:.1f}h"
                elif eta_seconds >= 60:
                    eta_str = f"{eta_seconds / 60:.1f}m"
                else:
                    eta_str = f"{eta_seconds:.0f}s"
            else:
                eta_str = "calculating..."

            elapsed_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed / 60:.1f}m"
            print(f"Progress: {completed}/{total_files} ({pct:.1f}%) | "
                  f"Processed: {files_processed} | Skipped: {files_skipped} | "
                  f"Elapsed: {elapsed_str} | ETA: {eta_str}")
            last_progress_time = current_time

    total_time = time.time() - start_time
    if total_time >= 3600:
        time_str = f"{total_time / 3600:.1f} hours"
    elif total_time >= 60:
        time_str = f"{total_time / 60:.1f} minutes"
    else:
        time_str = f"{total_time:.0f} seconds"

    print(f"\nDone in {time_str}:")
    print(f"  Files processed: {files_processed}")
    print(f"  Files skipped (unchanged): {files_skipped}")
    print(f"  Total chunks indexed: {total_chunks}")
    print(f"  Database: {args.output}")


if __name__ == "__main__":
    main()
