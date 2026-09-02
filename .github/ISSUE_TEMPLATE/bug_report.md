---
name: Bug report
about: Create a report to help boundless improve
title: "[BUG] "
labels: bug
assignees: ''
---

**Describe the bug**
A clear and concise description of what the bug is.

**To reproduce**
Steps to reproduce the behavior:
1. Drop a sample EPUB into `processing/inbox/`
2. Check the watcher state via `GET /api/health`
3. See error

**Expected behavior**
A clear and concise description of what you expected to happen.

**Screenshots / log output**
If applicable, add screenshots or paste the relevant server log.

**Environment (please complete the following information):**
- OS: [e.g. macOS 14, Ubuntu 24.04, Windows 11]
- Python version: [e.g. 3.12.5]
- boundless version: [e.g. 2.0.0]
- Installation method: [pip / pyinstaller / git clone]

**Sovereign checks**
- [ ] No `/mnt` paths in your config (`/settings` → `PROCESSING_DIR`)
- [ ] Settings file exists at repo root (`settings.json`)
- [ ] lxml installed (`pip show lxml`)
