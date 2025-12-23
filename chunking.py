"""Text chunking utilities for Markdown documentation."""

import re
from pathlib import Path


def parse_markdown_sections(text: str) -> list[tuple[str | None, str]]:
    """
    Split markdown into sections based on headers.
    Returns list of (title, content) tuples.
    """
    header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    sections = []
    last_end = 0
    last_title = None

    for match in header_pattern.finditer(text):
        if match.start() > last_end:
            content = text[last_end : match.start()].strip()
            if content:
                sections.append((last_title, content))
        last_title = match.group(2).strip()
        last_end = match.end()

    if last_end < len(text):
        content = text[last_end:].strip()
        if content:
            sections.append((last_title, content))

    if not sections and text.strip():
        sections.append((None, text.strip()))

    return sections


def chunk_text(text: str, chunk_size: int = 1500, chunk_overlap: int = 200) -> list[str]:
    """Split text into chunks respecting paragraph and sentence boundaries."""
    if not text or not text.strip():
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks = []
    paragraphs = re.split(r"\n\n+", text)

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

            if len(para) > chunk_size:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                current_chunk = ""
                for sent in sentences:
                    if len(current_chunk) + len(sent) + 1 <= chunk_size:
                        current_chunk = f"{current_chunk} {sent}" if current_chunk else sent
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        if len(sent) > chunk_size:
                            for i in range(0, len(sent), chunk_size - chunk_overlap):
                                chunks.append(sent[i : i + chunk_size])
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
            prev_chunk = chunks[i - 1]
            prev_end = (
                prev_chunk[-chunk_overlap:] if len(prev_chunk) > chunk_overlap else prev_chunk
            )
            overlapped.append(prev_end + " " + chunks[i])
        chunks = overlapped

    return chunks


def process_file(path: Path, base_dir: Path, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """Process a single markdown file into chunks."""
    text = path.read_text(encoding="utf-8", errors="replace")
    relative_path = str(path.relative_to(base_dir)).replace("\\", "/")

    sections = parse_markdown_sections(text)

    all_chunks = []
    chunk_index = 0

    for title, content in sections:
        text_chunks = chunk_text(content, chunk_size, chunk_overlap)

        for chunk_content in text_chunks:
            all_chunks.append(
                {
                    "id": f"{relative_path}:{chunk_index}",
                    "source": relative_path,
                    "title": title,
                    "content": chunk_content,
                    "chunk_index": chunk_index,
                }
            )
            chunk_index += 1

    return all_chunks
