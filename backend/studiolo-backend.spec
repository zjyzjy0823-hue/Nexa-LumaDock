# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'desktop_entry.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'alembic.ini'), '.'), (str(root / 'migrations'), 'migrations'),
           (str(root.parent / 'src' / 'data' / 'dashboard.json'), '.')],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
                   'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on',
                   'sqlalchemy.dialects.sqlite', 'alembic.runtime.migration',
                   'cryptography.hazmat.primitives.kdf.argon2',
                   'cryptography.hazmat.primitives.kdf.hkdf',
                   'cryptography.hazmat.primitives.ciphers.aead',
                   'app.space.routes', 'app.scheduler.routes'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='studiolo-backend',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False)
