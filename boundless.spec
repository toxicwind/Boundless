# PyInstaller spec — Boundless (Python-canonical layout)
# Build:  pyinstaller boundless.spec
from pathlib import Path

block_cipher = None

a = Analysis(
    ['src/boundless/cli.py'],
    pathex=['src', '.'],
    binaries=[],
    datas=[
        ('web/index.html', 'web'),
        ('web/app.css', 'web'),
        ('web/app.js', 'web'),
        ('web/settings.html', 'web'),
        ('web/settings.js', 'web'),
    ],
    hiddenimports=[
        'boundless', 'boundless.cli', 'boundless.epub', 'boundless.pdf', 'boundless.docx',
        'boundless.profile', 'boundless.toc_split', 'boundless.toc_parse', 'boundless.toc_build',
        'boundless.models', 'boundless.registry', 'boundless.universal', 'boundless.batch',
        'boundless.utils', 'boundless.mcp_server', 'boundless.db', 'boundless.deps',
        'web', 'web.server',
        'fastapi', 'uvicorn', 'multipart', 'lxml', 'pystray', 'PIL', 'mcp',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='boundless',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name='boundless')
