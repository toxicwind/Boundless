# Boundless

Boundless is an accessibility-first EPUB, PDF, and DOCX document splitter designed for educational and universal design needs.

## Features

- **Accessibility-First:** Compliant with ADA (Title II, Section 508) and IDEA standards.
- **Publisher-Aware:** Automatically creates profiles to handle specific publisher file structures.
- **Modular Pipeline:** Processes documents in a clean, file-system-safe pipeline.
- **Web UI:** Accessible interface running on port 10200.
- **MCP Server:** Model Context Protocol server exposing splitting, validation, and VPAT tools.

## Installation

```bash
# Clone the repository
git clone https://github.com/toxicwind/Boundless
cd Boundless

# Install with all format support
pip install -e ".[full]"

# Or minimal + specific formats
pip install -e ".[epub,pdf,docx]"
```

## Usage

### Command line

```bash
# Split a document
boundless input.epub -o ./output --max-mb 50

# Split by table of contents
boundless-toc input.epub -o ./output

# Launch the web UI
boundless-web

# Run the MCP server (stdio)
boundless-mcp
```

### Web interface

Start the web UI:

```bash
boundless-web
# or
python -m web.server
```

Then open http://127.0.0.1:10200. Drop EPUBs into `processing/inbox/` for autonomous processing.

### Python API

```python
from boundless import UniversalSplitter

splitter = UniversalSplitter(max_size_mb=50)
report = splitter.split("input.epub", "./output")
print(f"{len(report.chunks)} chunks")
```

## Development

```bash
pip install -e ".[full,dev]"
pytest tests/ -v
ruff check src/boundless web
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
