# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
backend_dir = Path(".").resolve().parent

a = Analysis(
    ["entrypoint.py"],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=[
        (str(backend_dir / "app"), "app"),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "aiosqlite",
        "sqlalchemy.dialects.sqlite",
        "app.main",
        "app.config",
        "app.db.engine",
        "app.db.models",
        "app.db.models_sqlite",
        "app.api.agents",
        "app.api.conversations",
        "app.api.objects",
        "app.api.robots",
        "app.api.tts",
        "app.api.stt",
        "app.api.heartbeat",
        "app.api.regenerate",
        "app.api.status",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["asyncpg", "pgvector", "redis"],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="nomi-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    target_arch="arm64",
)
