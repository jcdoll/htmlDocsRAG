# COMSOL Documentation Conversion

COMSOL's HTML documentation uses CSS classes (`Head1_DVD`, `Body_text_DVD`) instead of semantic HTML tags. The specialized Python script handles this structure correctly.

## Installation Options

When installing COMSOL, select:
- Install application libraries for selected products
- Install documentation relevant to selected products

## Documentation Location

COMSOL 6.4 HTML documentation default paths:

- **Windows:** `C:\Program Files\COMSOL\COMSOL64\Multiphysics\doc\help\wtpwebapps\ROOT\doc\`
- **Linux:** `/usr/local/comsol/multiphysics/doc/help/wtpwebapps/ROOT/doc`

The HTML files are spread across subdirectories (`comsol_ref_manual/`, `acdc_module/`, etc.).

## Conversion

### Windows

```powershell
uv run python scripts/convert_comsol_html.py "C:\Program Files\COMSOL\COMSOL64\Multiphysics\doc\help\wtpwebapps\ROOT\doc" ./markdown
uv run python build_index.py ./markdown --output db/comsol.db --no-embeddings
uv run python mcp_server.py --db db/comsol.db --test "mesh refinement"
uv run python build_index.py ./markdown --output db/comsol.db
```

### macOS/Linux

```bash
uv run python scripts/convert_comsol_html.py /usr/local/comsol/multiphysics/doc/help/wtpwebapps/ROOT/doc ./markdown
uv run python build_index.py ./markdown --output db/comsol.db --no-embeddings
uv run python mcp_server.py --db db/comsol.db --test "boundary conditions"
uv run python build_index.py ./markdown --output db/comsol.db
```

## Expected Output

A typical COMSOL 6.4 installation:
- 8,000 HTML files
- 72,000 chunks after indexing
- 250 MB database with embeddings
