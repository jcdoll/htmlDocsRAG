"""Database operations for documentation search and retrieval."""

import logging
import os
import sqlite3
import struct
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_SEARCH_MODES = ("keyword", "semantic", "hybrid")
_conn: sqlite3.Connection | None = None
_has_vec: bool = False
_embedding_model = None
_model_name: str = "BAAI/bge-small-en-v1.5"
_db_name: str = "documentation"


# --- Path utilities ---


def get_data_dir() -> Path:
    """Get the default data directory for database files."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "docs-mcp"


def resolve_db_path(db_arg: str) -> Path:
    """Resolve database path, checking default directory if not absolute."""
    db_path = Path(db_arg)
    if db_path.is_absolute() or db_path.exists():
        return db_path
    data_dir = get_data_dir()
    default_path = data_dir / db_arg
    return default_path if default_path.exists() else db_path


def list_databases() -> list[Path]:
    """List available databases in the default data directory."""
    data_dir = get_data_dir()
    return sorted(data_dir.glob("*.db")) if data_dir.exists() else []


# --- Connection management ---


def get_connection() -> sqlite3.Connection:
    """Get the database connection."""
    if _conn is None:
        raise RuntimeError("Database not initialized")
    return _conn


def get_db_name() -> str:
    """Get the friendly database name."""
    return _db_name


def set_model_name(name: str) -> None:
    """Set the embedding model name."""
    global _model_name
    _model_name = name


def get_embedding_model():
    """Lazy-load the embedding model."""
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"Loading embedding model: {_model_name}")
        from sentence_transformers import SentenceTransformer

        _embedding_model = SentenceTransformer(_model_name)
    return _embedding_model


def init_db(db_path: Path) -> None:
    """Initialize database connection."""
    global _conn, _has_vec, _db_name
    _db_name = db_path.stem.upper()
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
    try:
        import sqlite_vec

        _conn.enable_load_extension(True)
        sqlite_vec.load(_conn)
        _conn.enable_load_extension(False)
        _has_vec = True
    except Exception as e:
        logger.warning(f"sqlite-vec not available: {e}")
        _has_vec = False


def close_db() -> None:
    """Close the database connection."""
    global _conn
    if _conn is not None:
        try:
            _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        _conn.close()
        _conn = None


# --- Search primitives ---


def sanitize_fts_query(query: str) -> str:
    """Sanitize a query string for safe use with FTS5 MATCH."""
    tokens = query.split()
    if not tokens:
        return ""
    return " ".join(f'"{t.replace(chr(34), chr(34) + chr(34))}"' for t in tokens)


def search_fts(query: str, limit: int) -> list[tuple[str, float]]:
    """Full-text search using FTS5. Returns (chunk_id, score) pairs."""
    if not query or not query.strip():
        return []
    conn = get_connection()
    safe_query = sanitize_fts_query(query)
    if not safe_query:
        return []
    try:
        return conn.execute(
            """SELECT c.id, -bm25(chunks_fts, 1, 10) as score
               FROM chunks_fts JOIN chunks c ON chunks_fts.rowid = c.rowid
               WHERE chunks_fts MATCH ? ORDER BY score DESC LIMIT ?""",
            (safe_query, limit),
        ).fetchall()
    except sqlite3.OperationalError as e:
        logger.warning(f"FTS5 search error: {e}")
        return []


def search_vec(query: str, limit: int) -> list[tuple[str, float]]:
    """Vector similarity search. Returns (chunk_id, score) pairs."""
    if not _has_vec:
        return []
    try:
        model = get_embedding_model()
        embedding = model.encode([query])[0]
        blob = struct.pack(f"{len(embedding)}f", *embedding)
        sql = """SELECT id, distance FROM chunks_vec
                   WHERE embedding MATCH ? ORDER BY distance LIMIT ?"""
        results = get_connection().execute(sql, (blob, limit)).fetchall()
        return [(id, 1 / (1 + dist)) for id, dist in results]
    except Exception as e:
        logger.warning(f"Vector search error: {e}")
        return []


def reciprocal_rank_fusion(
    results_lists: list[list[tuple[str, float]]], k: int = 60
) -> list[tuple[str, float]]:
    """Combine ranked lists using RRF. k=60 from Cormack et al., 2009."""
    scores: dict[str, float] = {}
    for results in results_lists:
        for rank, (chunk_id, _) in enumerate(results):
            scores[chunk_id] = scores.get(chunk_id, 0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# --- Query functions ---


def search_docs(
    query: str, limit: int = 10, mode: str = "hybrid", source_filter: str | None = None
) -> list[dict]:
    """Search documentation with keyword, semantic, or hybrid mode.

    Args:
        source_filter: Optional substring to filter results by source path (e.g., "llmatlab").
    """
    if mode not in VALID_SEARCH_MODES:
        raise ValueError(f"Invalid mode '{mode}'. Must be one of: {VALID_SEARCH_MODES}")

    results_lists = []
    if mode in ("keyword", "hybrid") and (fts := search_fts(query, limit)):
        results_lists.append(fts)
    if mode in ("semantic", "hybrid") and _has_vec and (vec := search_vec(query, limit)):
        results_lists.append(vec)

    if not results_lists:
        return []

    if len(results_lists) == 1:
        combined = results_lists[0][:limit]
    else:
        combined = reciprocal_rank_fusion(results_lists)[:limit]

    chunk_ids = [cid for cid, _ in combined]
    scores = dict(combined)

    # Fetch chunk details
    conn = get_connection()
    placeholders = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"SELECT id, source, title, content, chunk_index FROM chunks WHERE id IN ({placeholders})",
        chunk_ids,
    ).fetchall()
    id_to_row = {r[0]: r for r in rows}

    results = [
        {
            "chunk_id": r[0],
            "source": r[1],
            "title": r[2],
            "content": r[3],
            "chunk_index": r[4],
            "score": scores.get(r[0], 0),
        }
        for cid in chunk_ids
        if (r := id_to_row.get(cid))
    ]

    if source_filter:
        results = [r for r in results if source_filter in r["source"]]

    return results


def get_chunk(chunk_id: str) -> dict | None:
    """Get a specific chunk by ID."""
    row = (
        get_connection()
        .execute(
            "SELECT id, source, title, content, chunk_index FROM chunks WHERE id = ?",
            (chunk_id,),
        )
        .fetchone()
    )
    if row:
        return {
            "chunk_id": row[0],
            "source": row[1],
            "title": row[2],
            "content": row[3],
            "chunk_index": row[4],
        }
    return None


def list_sources() -> list[dict]:
    """List all indexed source files."""
    rows = (
        get_connection()
        .execute("SELECT source, COUNT(*) FROM chunks GROUP BY source ORDER BY source")
        .fetchall()
    )
    return [{"path": r[0], "chunk_count": r[1]} for r in rows]


def list_modules() -> list[dict]:
    """List unique source path prefixes (modules/products) with file counts."""
    rows = (
        get_connection()
        .execute(
            """SELECT
                 CASE WHEN INSTR(source, '\\') > 0
                      THEN SUBSTR(source, 1, INSTR(source, '\\') - 1)
                      WHEN INSTR(source, '/') > 0
                      THEN SUBSTR(source, 1, INSTR(source, '/') - 1)
                      ELSE source END as module,
                 COUNT(DISTINCT source) as file_count,
                 COUNT(*) as chunk_count
               FROM chunks GROUP BY module ORDER BY module"""
        )
        .fetchall()
    )
    return [{"module": r[0], "file_count": r[1], "chunk_count": r[2]} for r in rows]


def search_sources(pattern: str, limit: int = 50) -> list[dict]:
    """Search source paths by substring pattern."""
    if not pattern or not pattern.strip():
        return []
    rows = (
        get_connection()
        .execute(
            """SELECT source, COUNT(*) as chunk_count FROM chunks
               WHERE source LIKE ? GROUP BY source ORDER BY source LIMIT ?""",
            (f"%{pattern}%", limit),
        )
        .fetchall()
    )
    return [{"path": r[0], "chunk_count": r[1]} for r in rows]


def get_context(chunk_id: str, before: int = 1, after: int = 1) -> dict:
    """Get a chunk with surrounding context from the same source file."""
    conn = get_connection()
    target = conn.execute(
        "SELECT id, source, title, content, chunk_index FROM chunks WHERE id = ?",
        (chunk_id,),
    ).fetchone()

    if not target:
        return {"target": None, "context": [], "error": f"Chunk not found: {chunk_id}"}

    source, idx = target[1], target[4]
    rows = conn.execute(
        """SELECT id, source, title, content, chunk_index FROM chunks
           WHERE source = ? AND chunk_index BETWEEN ? AND ? ORDER BY chunk_index""",
        (source, max(0, idx - before), idx + after),
    ).fetchall()

    context, target_dict = [], None
    for r in rows:
        d = {"chunk_id": r[0], "source": r[1], "title": r[2], "content": r[3], "chunk_index": r[4]}
        (target_dict := d) if r[0] == chunk_id else context.append(d)

    return {"target": target_dict, "context": context}


def get_source(source_path: str, offset: int = 0, limit: int | None = None) -> dict:
    """Get all chunks from a source file."""
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM chunks WHERE source = ?", (source_path,)).fetchone()[
        0
    ]

    if total == 0:
        return {"chunks": [], "total": 0, "error": f"Source not found: {source_path}"}

    sql = """SELECT id, source, title, content, chunk_index
             FROM chunks WHERE source = ? ORDER BY chunk_index"""
    params = [source_path]
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    elif offset > 0:
        sql += " LIMIT -1 OFFSET ?"
        params.append(offset)

    rows = conn.execute(sql, params).fetchall()
    chunks = [
        {"chunk_id": r[0], "source": r[1], "title": r[2], "content": r[3], "chunk_index": r[4]}
        for r in rows
    ]
    return {"chunks": chunks, "total": total, "offset": offset}


def list_sections(source_path: str) -> list[dict]:
    """List all section titles in a source file with their first chunk ID."""
    rows = (
        get_connection()
        .execute(
            """SELECT title, MIN(id) as chunk_id, MIN(chunk_index) as chunk_index
               FROM chunks WHERE source = ? GROUP BY title ORDER BY MIN(chunk_index)""",
            (source_path,),
        )
        .fetchall()
    )
    return [{"title": r[0], "chunk_id": r[1], "chunk_index": r[2]} for r in rows]


def get_chunk_by_title(source_path: str, title: str) -> list[dict]:
    """Get all chunks with a specific title from a source file."""
    rows = (
        get_connection()
        .execute(
            """SELECT id, source, title, content, chunk_index FROM chunks
               WHERE source = ? AND title = ? ORDER BY chunk_index""",
            (source_path, title),
        )
        .fetchall()
    )
    return [
        {"chunk_id": r[0], "source": r[1], "title": r[2], "content": r[3], "chunk_index": r[4]}
        for r in rows
    ]


def search_symbols(prefix: str, limit: int = 50) -> list[dict]:
    """Search for API/function symbols by prefix (e.g., 'mph', 'model.').

    Uses FTS5 prefix matching to find chunks containing symbols starting with prefix.
    """
    if not prefix or not prefix.strip():
        return []
    conn = get_connection()
    # FTS5 prefix search with * suffix
    safe_prefix = prefix.replace('"', '""')
    try:
        rows = conn.execute(
            """SELECT c.id, c.source, c.title, c.content, -bm25(chunks_fts, 1, 10) as score
               FROM chunks_fts JOIN chunks c ON chunks_fts.rowid = c.rowid
               WHERE chunks_fts MATCH ? ORDER BY score DESC LIMIT ?""",
            (f'"{safe_prefix}"*', limit),
        ).fetchall()
        return [
            {"chunk_id": r[0], "source": r[1], "title": r[2], "content": r[3], "score": r[4]}
            for r in rows
        ]
    except sqlite3.OperationalError as e:
        logger.warning(f"Symbol search error: {e}")
        return []
