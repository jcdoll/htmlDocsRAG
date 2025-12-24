#!/usr/bin/env python3
"""
Fetch documentation from ReadTheDocs (or similar) by crawling from a base URL.

Usage:
    fetch_rtd_docs.py <base_url> <output_dir>

Examples:
    fetch_rtd_docs.py https://mph.readthedocs.io/en/stable/ ./markdown/MPh
    fetch_rtd_docs.py https://docs.example.com/latest/ ./markdown/example
"""

import argparse
import subprocess
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse


class LinkExtractor(HTMLParser):
    """Extract href attributes from anchor tags."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


class ContentExtractor(HTMLParser):
    """Extract main content from HTML, skipping navigation/chrome."""

    def __init__(self):
        super().__init__()
        self.content = []
        self.in_content = False
        self.depth = 0
        self.content_tags = {"article", "main"}
        # Tags to skip even inside content
        self.skip_tags = {"nav", "script", "style", "header", "footer"}
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.content_tags and not self.in_content:
            self.in_content = True
            self.depth = 1
            return

        if self.in_content:
            if tag in self.skip_tags:
                self.skip_depth += 1
            if self.skip_depth == 0:
                attr_str = ""
                for name, value in attrs:
                    attr_str += f' {name}="{value}"'
                self.content.append(f"<{tag}{attr_str}>")
            self.depth += 1

    def handle_endtag(self, tag):
        if self.in_content:
            self.depth -= 1
            if tag in self.skip_tags and self.skip_depth > 0:
                self.skip_depth -= 1
            elif self.skip_depth == 0:
                self.content.append(f"</{tag}>")
            if self.depth == 0:
                self.in_content = False

    def handle_data(self, data):
        if self.in_content and self.skip_depth == 0:
            self.content.append(data)

    def get_content(self) -> str:
        return "".join(self.content)


def extract_content(html: bytes) -> bytes:
    """Extract main content from HTML page."""
    parser = ContentExtractor()
    try:
        parser.feed(html.decode("utf-8", errors="ignore"))
        content = parser.get_content()
        if content.strip():
            return content.encode("utf-8")
    except Exception:
        pass
    # Fallback to full HTML if extraction fails
    return html


def fetch_page(url: str) -> bytes | None:
    """Fetch a page and return its content."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "docs-mcp-fetcher")

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read()
    except urllib.error.URLError as e:
        print(f"  Failed to fetch {url}: {e}")
        return None


def extract_links(html: bytes, base_url: str) -> list[str]:
    """Extract and resolve all links from HTML content."""
    parser = LinkExtractor()
    try:
        parser.feed(html.decode("utf-8", errors="ignore"))
    except Exception:
        return []

    links = []
    for href in parser.links:
        # Skip anchors, javascript, mailto, etc.
        if href.startswith(("#", "javascript:", "mailto:")):
            continue

        # Resolve relative URLs
        absolute = urljoin(base_url, href)

        # Strip anchors and query params
        parsed = urlparse(absolute)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        links.append(clean_url)

    return links


def html_to_markdown(html_content: bytes) -> str | None:
    """Convert HTML to Markdown using pandoc."""
    # Extract main content first
    content = extract_content(html_content)

    try:
        result = subprocess.run(
            ["pandoc", "-f", "html", "-t", "gfm", "--wrap=none"],
            input=content,
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.decode("utf-8")
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        print("Error: pandoc is required but not installed.")
        sys.exit(1)
    return None


def url_to_filepath(url: str, base_url: str) -> str:
    """Convert URL to relative filepath."""
    # Remove base URL prefix
    base_parsed = urlparse(base_url)
    url_parsed = urlparse(url)

    # Get path relative to base
    base_path = base_parsed.path.rstrip("/")
    url_path = url_parsed.path

    if url_path.startswith(base_path):
        rel_path = url_path[len(base_path) :].lstrip("/")
    else:
        rel_path = url_path.lstrip("/")

    # Handle index pages
    if not rel_path or rel_path.endswith("/"):
        rel_path = rel_path.rstrip("/") + "/index"

    # Change extension
    if rel_path.endswith(".html"):
        rel_path = rel_path[:-5]

    return rel_path + ".md"


def crawl_docs(base_url: str, output_dir: Path) -> int:
    """Crawl documentation starting from base_url."""
    # Normalize base URL
    if not base_url.endswith("/"):
        base_url += "/"

    visited = set()
    queue = [base_url]
    count = 0

    while queue:
        url = queue.pop(0)

        # Skip if already visited
        if url in visited:
            continue
        visited.add(url)

        # Only process URLs under base_url
        if not url.startswith(base_url):
            continue

        # Only process HTML pages
        if not (url.endswith(".html") or url.endswith("/") or url == base_url):
            continue

        # Skip source code pages
        if "/_modules/" in url or "/_sources/" in url:
            continue

        # Fetch page
        html = fetch_page(url)
        if html is None:
            continue

        # Convert to markdown
        markdown = html_to_markdown(html)
        if markdown is None:
            continue

        # Save file
        rel_path = url_to_filepath(url, base_url)
        out_file = output_dir / rel_path
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(markdown, encoding="utf-8")
        print(f"  {rel_path}")
        count += 1

        # Extract and queue new links
        for link in extract_links(html, url):
            if link not in visited and link.startswith(base_url):
                queue.append(link)

    return count


def main():
    parser = argparse.ArgumentParser(
        description="Fetch documentation by crawling from a base URL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s https://mph.readthedocs.io/en/stable/ ./markdown/MPh
  %(prog)s https://docs.example.com/latest/ ./markdown/example
        """,
    )
    parser.add_argument(
        "base_url",
        help="Base URL to start crawling from",
    )
    parser.add_argument(
        "output_dir",
        help="Local directory to save converted markdown files",
    )

    args = parser.parse_args()

    # Check for pandoc
    try:
        subprocess.run(["pandoc", "--version"], capture_output=True, check=True, timeout=5)
    except FileNotFoundError:
        print("Error: pandoc is required but not installed.")
        print("Install with: brew install pandoc (macOS) or apt install pandoc (Ubuntu)")
        sys.exit(1)
    except subprocess.CalledProcessError:
        pass

    output_dir = Path(args.output_dir)
    print(f"Crawling docs from {args.base_url}")
    print(f"Output directory: {output_dir}")
    print()

    count = crawl_docs(args.base_url, output_dir)

    print()
    print(f"Done. Fetched and converted {count} pages.")


if __name__ == "__main__":
    main()
