# Boundless

Boundless is an accessibility-first EPUB, PDF, and DOCX document splitter designed for educational and universal design needs.

## Features

- **Accessibility-First:** Compliant with ADA (Title II, Section 508) and IDEA standards.
- **Publisher-Aware:** Automatically creates profiles to handle specific publisher file structures.
- **Modular Pipeline:** Processes documents in a clean, file-system-safe pipeline.
- **Web UI:** Accessible interface running on port 10200.

## Installation

```bash
# Clone the repository
git clone https://github.com/toxicwind/boundless
cd boundless

# Install dependencies
pip install -r requirements.txt
# OR
bun install
```

## Usage

Start the web interface:

```bash
python -m boundless.server
# OR
bun run server
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
