# PyInstaller spec — cross-platform (macOS/Windows/Linux)
# Build:  pyinstaller boundless.spec
import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['boundless.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('web/index.html', 'web'),
        ('web/app.css', 'web'),
        ('web/app.js', 'web'),
        ('web/settings.html', 'web'),
        ('web/settings.js', 'web'),
        ('settings.json', '.'),
        ('src/ada_splitter', 'ada_splitter'),
    ],
    hiddenimports=[
        'ada_splitter', 'ada_splitter.epub', 'ada_splitter.pdf', 'ada_splitter.docx',
        'ada_splitter.profile', 'ada_splitter.toc_split', 'ada_splitter.toc_parse', 'ada_splitter.toc_build',
        'ada_splitter.models', 'ada_splitter.registry', 'ada_splitter.universal', 'ada_splitter.batch',
        'ada_splitter.utils', 'ada_splitter.mcp_server',
        'fastapi', 'uvicorn', 'multipart', 'lxml', 'pystray', 'PIL',
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
