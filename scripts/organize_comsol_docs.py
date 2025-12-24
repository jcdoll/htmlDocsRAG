#!/usr/bin/env python3
"""
Reorganize COMSOL markdown folders to cleaner structure.

Transforms:
  com.comsol.help.mems/ -> mems/
  com.comsol.help.models.aco.absorptive_muffler/ -> models/aco/absorptive_muffler/

Usage:
    organize_comsol_docs.py <markdown_dir>

Example:
    organize_comsol_docs.py ./markdown
"""

import argparse
import shutil
import sys
from pathlib import Path


def organize_docs(markdown_dir: Path) -> tuple[int, int]:
    """Reorganize COMSOL doc folders. Returns (modules_moved, models_moved)."""
    modules_moved = 0
    models_moved = 0

    # Collect folders to move (don't modify while iterating)
    moves = []

    for folder in markdown_dir.iterdir():
        if not folder.is_dir():
            continue

        name = folder.name

        if name.startswith("com.comsol.help.models."):
            # com.comsol.help.models.aco.absorptive_muffler → models/aco/absorptive_muffler
            parts = name.split(".")
            if len(parts) >= 6:
                # parts = [com, comsol, help, models, aco, absorptive_muffler]
                module = parts[4]
                model = ".".join(parts[5:])  # Handle names with dots
                new_path = markdown_dir / "models" / module / model
                moves.append((folder, new_path, "model"))

        elif name.startswith("com.comsol.help."):
            # com.comsol.help.mems → mems
            new_name = name.removeprefix("com.comsol.help.")
            new_path = markdown_dir / new_name
            moves.append((folder, new_path, "module"))

    # Execute moves
    for old_path, new_path, move_type in moves:
        if new_path.exists():
            print(f"  Warning: {new_path} already exists, skipping {old_path.name}")
            continue

        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_path), str(new_path))

        if move_type == "model":
            models_moved += 1
        else:
            modules_moved += 1
            print(f"  {old_path.name} -> {new_path.relative_to(markdown_dir)}")

    return modules_moved, models_moved


def main():
    parser = argparse.ArgumentParser(
        description="Reorganize COMSOL markdown folders to cleaner structure.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Transforms:
  com.comsol.help.mems/ -> mems/
  com.comsol.help.models.aco.absorptive_muffler/ -> models/aco/absorptive_muffler/
        """,
    )
    parser.add_argument(
        "markdown_dir",
        help="Directory containing COMSOL markdown folders",
    )

    args = parser.parse_args()
    markdown_dir = Path(args.markdown_dir)

    if not markdown_dir.is_dir():
        print(f"Error: {markdown_dir} is not a directory")
        sys.exit(1)

    print(f"Reorganizing COMSOL docs in {markdown_dir}")
    print()

    modules_moved, models_moved = organize_docs(markdown_dir)

    print()
    print(f"Done. Moved {modules_moved} module folders, {models_moved} model folders.")


if __name__ == "__main__":
    main()
