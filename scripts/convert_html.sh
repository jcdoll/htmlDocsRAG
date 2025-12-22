#!/usr/bin/env bash
#
# Convert HTML documentation to Markdown.
#
# Usage: ./convert_html.sh <source_dir> <output_dir>
#
# Recursively finds all .html and .htm files in source_dir,
# converts them to GitHub-Flavored Markdown, and preserves
# the directory structure in output_dir.

set -euo pipefail

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <source_dir> <output_dir>" >&2
    exit 1
fi

SOURCE_DIR="$1"
OUTPUT_DIR="$2"

if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "Error: Source directory does not exist: $SOURCE_DIR" >&2
    exit 1
fi

# Check for pandoc
if ! command -v pandoc &> /dev/null; then
    echo "Error: pandoc is required but not installed." >&2
    echo "Install with: brew install pandoc (macOS) or apt install pandoc (Ubuntu)" >&2
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Normalize paths (remove trailing slashes)
SOURCE_DIR="${SOURCE_DIR%/}"
OUTPUT_DIR="${OUTPUT_DIR%/}"

# Count files for progress
total=$(find "$SOURCE_DIR" -type f \( -name "*.html" -o -name "*.htm" \) | wc -l)
count=0
errors=0

echo "Converting $total HTML files from $SOURCE_DIR to $OUTPUT_DIR"

# Process each HTML file
while IFS= read -r -d '' html_file; do
    ((count++)) || true
    
    # Compute relative path
    rel_path="${html_file#$SOURCE_DIR/}"
    
    # Change extension to .md
    md_path="${rel_path%.html}"
    md_path="${md_path%.htm}.md"
    
    # Full output path
    out_file="$OUTPUT_DIR/$md_path"
    out_dir="$(dirname "$out_file")"
    
    # Create output directory
    mkdir -p "$out_dir"
    
    # Convert
    if pandoc -f html -t gfm --wrap=none "$html_file" -o "$out_file" 2>/dev/null; then
        printf "\r[%d/%d] Converted: %s" "$count" "$total" "$rel_path"
    else
        printf "\r[%d/%d] FAILED: %s\n" "$count" "$total" "$rel_path"
        ((errors++)) || true
    fi
done < <(find "$SOURCE_DIR" -type f \( -name "*.html" -o -name "*.htm" \) -print0)

echo ""
echo "Done. Converted $((count - errors)) files, $errors errors."
