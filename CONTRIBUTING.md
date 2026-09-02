# Contributing to boundless

Boundless means:
- No `/mnt` paths anywhere. Use `pathlib` + `~`-expansion.
- No container-absolute paths (`/var/lib/...`, `/app/...`).
- All user data lives under `processing/` and `profiles/` next to the binary.
- Settings live in `settings.json` (auto-created on first run).

## Development

```bash
git clone https://github.com/toxicwind/boundless
cd boundless
python -m venv .venv && source .venv/bin/activate
pip install -e ".[full,dev]"
playwright install --with-deps chromium
pytest tests/ -v
```

## Filing issues

Use the [bug report](.github/ISSUE_TEMPLATE/bug_report.md) and [feature request](.github/ISSUE_TEMPLATE/feature_request.md) templates.

## Pull requests

- Add a test for every new code path.
- Keep modules file-split (no monoliths bigger than 500 lines).
- Brand = `boundless` (ADA + IDEA + i18n).
- Auto-profile + autonomous inbox must remain backwards compatible.
