#!/usr/bin/env python3
"""
Convert Comsol HTML documentation to Markdown.

Usage: python convert_html.py <source_dir> <output_dir>

Uses BeautifulSoup to properly handle Comsol's CSS-class-based structure
where divs with classes like Head1_DVD, Body_text_DVD are used instead
of semantic HTML tags.
"""

import sys
import re
import warnings
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

# Suppress XML parsing warnings for HTML files
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def get_text_content(element):
    """Extract text from an element, handling nested tags."""
    if element is None:
        return ""
    # Get all text, normalize whitespace
    text = element.get_text(separator=" ", strip=True)
    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def convert_html_to_markdown(html_content: str, source_path: str = "") -> str:
    """Convert Comsol HTML to clean Markdown."""
    soup = BeautifulSoup(html_content, 'lxml')
    
    # Extract title from <title> tag
    title_tag = soup.find('title')
    title = ""
    if title_tag:
        title = title_tag.get_text(strip=True)
        # Clean up "COMSOL 6.4 - " prefix
        title = re.sub(r'^COMSOL\s+[\d.]+\s*[-–—]\s*', '', title)
    
    # Find body content
    body = soup.find('body')
    if not body:
        return ""
    
    lines = []
    
    # Add title as H1 if we have one
    if title:
        lines.append(f"# {title}")
        lines.append("")
    
    # Process all divs with classes (not just direct children - content may be nested)
    for div in body.find_all('div', class_=True):
        class_list = div.get('class', [])
        class_name = class_list[0] if class_list else ""
        text = get_text_content(div)
        
        if not text:
            # Check for images
            img = div.find('img')
            if img and img.get('src'):
                src = img.get('src', '')
                alt = img.get('alt', 'Image')
                lines.append(f"![{alt}]({src})")
                lines.append("")
            continue
        
        # Map CSS classes to Markdown
        if class_name.startswith('Head1'):
            lines.append(f"# {text}")
            lines.append("")
        elif class_name.startswith('Head2'):
            lines.append(f"## {text}")
            lines.append("")
        elif class_name.startswith('Head3'):
            lines.append(f"### {text}")
            lines.append("")
        elif class_name.startswith('Head4'):
            lines.append(f"#### {text}")
            lines.append("")
        elif class_name.startswith('Head5') or class_name.startswith('Head6'):
            lines.append(f"##### {text}")
            lines.append("")
        elif 'FigureTitle' in class_name or 'TableTitle' in class_name:
            # Figure/table captions - italicize
            lines.append(f"*{text}*")
            lines.append("")
        elif 'Code' in class_name or 'Monospace' in class_name:
            # Code blocks
            lines.append(f"```")
            lines.append(text)
            lines.append("```")
            lines.append("")
        elif 'Note' in class_name or 'Warning' in class_name or 'Tip' in class_name:
            # Notes/warnings
            lines.append(f"> **Note:** {text}")
            lines.append("")
        elif 'Bullet' in class_name or 'List' in class_name:
            # List items
            lines.append(f"- {text}")
        elif class_name.startswith('Body') or class_name.startswith('Para'):
            # Regular paragraph
            lines.append(text)
            lines.append("")
        else:
            # Default: treat as paragraph
            if text:
                lines.append(text)
                lines.append("")
    
    result = '\n'.join(lines)
    # Clean up excessive newlines
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


def convert_file(args):
    """Convert a single HTML file to Markdown."""
    html_path, output_path = args
    try:
        html_content = html_path.read_text(encoding='utf-8', errors='replace')
        markdown = convert_html_to_markdown(html_content, str(html_path))
        
        if markdown:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(markdown, encoding='utf-8')
            return True, str(html_path)
        return False, f"Empty result: {html_path}"
    except Exception as e:
        return False, f"Error {html_path}: {e}"


def main():
    if len(sys.argv) < 3:
        print("Usage: python convert_html.py <source_dir> <output_dir>")
        sys.exit(1)
    
    source_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    
    if not source_dir.exists():
        print(f"Error: Source directory does not exist: {source_dir}")
        sys.exit(1)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all HTML files
    html_files = list(source_dir.rglob("*.html")) + list(source_dir.rglob("*.htm"))
    total = len(html_files)
    print(f"Found {total} HTML files to convert")
    
    # Prepare conversion tasks
    tasks = []
    for html_path in html_files:
        rel_path = html_path.relative_to(source_dir)
        md_path = output_dir / rel_path.with_suffix('.md')
        tasks.append((html_path, md_path))
    
    # Convert files in parallel
    converted = 0
    errors = 0
    
    with ProcessPoolExecutor() as executor:
        futures = {executor.submit(convert_file, task): task for task in tasks}
        
        for future in as_completed(futures):
            success, msg = future.result()
            if success:
                converted += 1
            else:
                errors += 1
            
            # Progress update every 500 files
            done = converted + errors
            if done % 500 == 0 or done == total:
                print(f"Progress: {done}/{total} ({converted} converted, {errors} errors)")
    
    print(f"\nDone! Converted {converted} files, {errors} errors.")


if __name__ == "__main__":
    main()

