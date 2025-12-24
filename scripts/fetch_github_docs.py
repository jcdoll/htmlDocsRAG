#!/usr/bin/env python3
"""
Fetch Markdown documentation from a GitHub repository.

Usage:
    fetch_github_docs.py <owner/repo> <docs_path> <output_dir> [--ref <branch>]

Examples:
    fetch_github_docs.py MPh-py/MPh docs ./markdown/mph
    fetch_github_docs.py some-org/lib documentation ./markdown/lib --ref v2.0
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def fetch_contents(owner: str, repo: str, path: str, ref: str) -> list[dict]:
    """Fetch directory contents via GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "docs-mcp-fetcher")

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"Error: Path '{path}' not found in {owner}/{repo}@{ref}")
        elif e.code == 403:
            print("Error: GitHub API rate limit exceeded. Try again later.")
        else:
            print(f"Error: GitHub API returned {e.code}")
        sys.exit(1)


def download_file(url: str, dest: Path) -> bool:
    """Download a file from URL to destination."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "docs-mcp-fetcher")

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(response.read())
            return True
    except urllib.error.URLError as e:
        print(f"  Failed to download {url}: {e}")
        return False


def fetch_docs(
    owner: str,
    repo: str,
    docs_path: str,
    output_dir: Path,
    ref: str,
    base_path: str = "",
) -> int:
    """Recursively fetch all .md files from a GitHub directory."""
    current_path = f"{docs_path}/{base_path}".rstrip("/")
    contents = fetch_contents(owner, repo, current_path, ref)

    count = 0
    for item in contents:
        name = item["name"]
        item_type = item["type"]

        if item_type == "dir":
            # Recurse into subdirectories
            sub_path = f"{base_path}/{name}".lstrip("/")
            count += fetch_docs(owner, repo, docs_path, output_dir, ref, sub_path)

        elif item_type == "file" and name.endswith(".md"):
            # Download markdown files
            rel_path = f"{base_path}/{name}".lstrip("/")
            dest = output_dir / rel_path

            download_url = item.get("download_url")
            if download_url and download_file(download_url, dest):
                print(f"  {rel_path}")
                count += 1

    return count


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Markdown documentation from a GitHub repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s MPh-py/MPh docs ./markdown/mph
  %(prog)s some-org/lib documentation ./markdown/lib --ref v2.0
        """,
    )
    parser.add_argument(
        "repo",
        help="GitHub repository in 'owner/repo' format",
    )
    parser.add_argument(
        "docs_path",
        help="Path to docs directory within the repository",
    )
    parser.add_argument(
        "output_dir",
        help="Local directory to save downloaded files",
    )
    parser.add_argument(
        "--ref",
        default="main",
        help="Git ref (branch, tag, or commit) to fetch from (default: main)",
    )

    args = parser.parse_args()

    # Parse owner/repo
    if "/" not in args.repo:
        print(f"Error: Repository must be in 'owner/repo' format, got '{args.repo}'")
        sys.exit(1)

    owner, repo = args.repo.split("/", 1)
    output_dir = Path(args.output_dir)

    print(f"Fetching docs from {owner}/{repo}@{args.ref}:{args.docs_path}")
    print(f"Output directory: {output_dir}")
    print()

    count = fetch_docs(owner, repo, args.docs_path, output_dir, args.ref)

    print()
    print(f"Done. Fetched {count} markdown files.")


if __name__ == "__main__":
    main()
