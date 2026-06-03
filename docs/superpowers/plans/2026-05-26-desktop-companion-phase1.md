# Nomi 桌面陪伴器 Phase 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal working macOS desktop companion app — Unity transparent window with a character avatar, system tray, text chat via bubbles, communicating with the existing Python backend adapted for SQLite.

**Architecture:** Unity client (transparent window + tray) launches a bundled Python FastAPI backend as a subprocess. Communication over localhost HTTP. Database switched from PostgreSQL to SQLite. Redis removed (unused in code).

**Tech Stack:** Unity 2022 LTS (C#), Python 3.11+ (FastAPI), SQLite (aiosqlite), PyInstaller

---

## File Structure

### Backend changes (existing codebase)

```
backend/
  app/
    config.py                    # MODIFY: add SQLite database URL support
    db/
      engine.py                  # MODIFY: SQLite-compatible engine creation
      models.py                  # MODIFY: replace PG-specific types with portable types
      models_sqlite.py           # CREATE: SQLite-specific column types (JSON for ARRAY/JSONB, blob for vector)
    services/
      memory.py                  # MODIFY: replace pgvector cosine_distance with numpy fallback
      cache.py                   # CREATE: in-memory TTL cache to replace Redis
    api/
      status.py                  # CREATE: health check + version endpoint
  desktop/
    build.py                     # CREATE: PyInstaller build script
    nomi.spec                    # CREATE: PyInstaller spec file
    entrypoint.py                # CREATE: desktop-mode entry point (sets env, launches uvicorn)
  requirements-desktop.txt       # CREATE: desktop-specific deps (aiosqlite, numpy, no asyncpg/pgvector/redis)
```

### Unity project (new)

```
desktop/
  NomiCompanion/                 # Unity project root
    Assets/
      Scripts/
        Core/
          AppManager.cs          # App lifecycle, backend process management
          BackendClient.cs       # HTTP client for FastAPI backend
          TrayManager.cs         # macOS menu bar tray icon
        UI/
          ChatBubble.cs          # Single chat bubble component
          ChatPanel.cs           # Chat bubble container + input
          FloatingWindow.cs      # Transparent always-on-top window controller
          AvatarDisplay.cs       # Character avatar rendering + simple idle animation
        Models/
          ApiModels.cs           # C# data classes matching backend API responses
      Plugins/
        macOS/
          TrayPlugin.bundle      # Native macOS tray icon plugin (Objective-C)
      Resources/
        Prefabs/
          ChatBubble.prefab      # Chat bubble prefab
        Sprites/
          default_avatar.png     # Placeholder avatar
      Scenes/
        Main.unity               # Main scene
    ProjectSettings/             # Unity project settings (auto-generated)
```

---

## Task 1: Backend — SQLite-compatible column types

**Files:**
- Create: `backend/app/db/models_sqlite.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_models_sqlite.py`

**Context:** The current models use PostgreSQL-specific types: `JSONB`, `ARRAY(Text)`, `ARRAY(Uuid)`, `Vector(768)`. SQLite doesn't support these. We need portable type adapters.

- [ ] **Step 1: Create SQLite-compatible type module**

Create `backend/app/db/models_sqlite.py`:

```python
"""
SQLite-compatible column types that replace PostgreSQL-specific types.
When using PostgreSQL, the original types are used.
When using SQLite, these portable alternatives are used.
"""
import json
from sqlalchemy import JSON, Text, TypeDecorator


class PortableJSON(TypeDecorator):
    """Uses JSONB on PostgreSQL, JSON on SQLite."""
    impl = JSON
    cache_ok = True


class PortableArray(TypeDecorator):
    """Stores arrays as JSON on SQLite, uses ARRAY on PostgreSQL."""
    impl = Text
    cache_ok = True

    def __init__(self, item_type=None):
        super().__init__()
        self.item_type = item_type

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps([str(v) for v in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)


class PortableVector(TypeDecorator):
    """Stores embedding vectors as JSON text on SQLite."""
    impl = Text
    cache_ok = True

    def __init__(self, dimensions=None):
        super().__init__()
        self.dimensions = dimensions

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)
```

- [ ] **Step 2: Add database mode flag to config**

In `backend/app/config.py`, add a computed property:

```python
class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://nomi:nomi@localhost:5432/nomi?ssl=disable"
    redis_url: str = "redis://localhost:6380/0"
    llm_provider: str = "claude-cli"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    embedding_dimensions: int = 768
    cors_origins: list[str] = ["http://localhost:3100", "https://nomi.zhuchao.life", "https://nomi-api.zhuchao.life"]

    model_config = {"env_prefix": "NOMI_"}

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url
```

- [ ] **Step 3: Update models.py to use portable types when on SQLite**

Replace the imports and column definitions in `backend/app/db/models.py`. The key changes:

At the top of models.py, replace the type imports:

```python
import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Float,
    ForeignKey,
    Integer,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings

if settings.is_sqlite:
    from app.db.models_sqlite import PortableJSON as JSONB_TYPE
    from app.db.models_sqlite import PortableArray, PortableVector

    def ArrayType(item_type):
        return PortableArray(item_type)

    def VectorType(dim):
        return PortableVector(dim)
else:
    from pgvector.sqlalchemy import Vector
    from sqlalchemy import ARRAY
    from sqlalchemy.dialects.postgresql import JSONB

    JSONB_TYPE = JSONB

    def ArrayType(item_type):
        return ARRAY(item_type)

    def VectorType(dim):
        return Vector(dim)
```

Then replace all column type usages:
- `JSONB` → `JSONB_TYPE`
- `ARRAY(Text)` → `ArrayType(Text)`
- `ARRAY(Uuid)` → `ArrayType(Uuid)`
- `Vector(settings.embedding_dimensions)` → `VectorType(settings.embedding_dimensions)`

For example, in the `Robot` class:
```python
personality: Mapped[dict | None] = mapped_column(JSONB_TYPE)
speaking_style: Mapped[dict | None] = mapped_column(JSONB_TYPE)
voice_profile: Mapped[dict | None] = mapped_column(JSONB_TYPE)
current_emotion: Mapped[dict | None] = mapped_column(JSONB_TYPE)
portrait: Mapped[dict | None] = mapped_column(JSONB_TYPE)
generation_stats: Mapped[dict | None] = mapped_column(JSONB_TYPE)
relationships_snapshot: Mapped[list | None] = mapped_column(JSONB_TYPE)
```

In `YearlyMemory`:
```python
emotional_impact: Mapped[dict | None] = mapped_column(JSONB_TYPE)
personality_effect: Mapped[dict | None] = mapped_column(JSONB_TYPE)
symbolic_tags: Mapped[list[str] | None] = mapped_column(ArrayType(Text))
```

In `Memory`:
```python
emotional_tags: Mapped[list[str] | None] = mapped_column(ArrayType(Text))
symbolic_tags: Mapped[list[str] | None] = mapped_column(ArrayType(Text))
related_robot_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ArrayType(Uuid))
embedding = mapped_column(VectorType(settings.embedding_dimensions), nullable=True)
```

In `RobotSkill`:
```python
trigger_keywords: Mapped[list[str] | None] = mapped_column(ArrayType(Text))
```

In `ObjectObservation`:
```python
symbolic_tags: Mapped[list[str] | None] = mapped_column(ArrayType(Text))
robot_reactions: Mapped[dict | None] = mapped_column(JSONB_TYPE)
```

And similar for all other JSONB/ARRAY usages across models.

- [ ] **Step 4: Write test to verify models create on SQLite**

Create `backend/tests/test_models_sqlite.py`:

```python
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.db.models import Base


@pytest.fixture
def sqlite_engine(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


def test_all_tables_created(sqlite_engine):
    inspector = inspect(sqlite_engine)
    table_names = inspector.get_table_names()
    expected = [
        "users", "robots", "yearly_memories", "memories",
        "activity_logs", "relationships", "conversations",
        "messages", "robot_skills", "object_observations",
    ]
    for table in expected:
        assert table in table_names, f"Table {table} not created"


def test_insert_and_read_robot(sqlite_engine):
    import uuid
    from app.db.models import User, Robot

    with Session(sqlite_engine) as session:
        user = User(id=uuid.uuid4(), name="test")
        session.add(user)
        session.flush()

        robot = Robot(
            id=uuid.uuid4(),
            user_id=user.id,
            name="TestBot",
            personality={"trait": "friendly"},
            speaking_style={"tone": "warm"},
        )
        session.add(robot)
        session.commit()

        fetched = session.get(Robot, robot.id)
        assert fetched.name == "TestBot"
        assert fetched.personality == {"trait": "friendly"}
```

- [ ] **Step 5: Run test**

Run: `cd /Users/chao/Documents/Projects/nomi && NOMI_DATABASE_URL="sqlite+aiosqlite:///test.db" python -m pytest backend/tests/test_models_sqlite.py -v`

Expected: PASS — all tables created, insert/read works.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models_sqlite.py backend/app/db/models.py backend/app/config.py backend/tests/test_models_sqlite.py
git commit -m "feat(desktop): add SQLite-compatible column types for desktop mode"
```

---

## Task 2: Backend — SQLite vector search fallback

**Files:**
- Modify: `backend/app/services/memory.py`
- Test: `backend/tests/test_memory_sqlite.py`

**Context:** The current `search_memories` uses `Memory.embedding.cosine_distance()` from pgvector. On SQLite, we compute cosine similarity in Python using numpy.

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_memory_sqlite.py`:

```python
import numpy as np
from app.services.memory import cosine_similarity


def test_cosine_similarity_identical():
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_opposite():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(-1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_memory_sqlite.py -v`

Expected: FAIL — `cosine_similarity` not importable.

- [ ] **Step 3: Add cosine_similarity and refactor search_memories**

In `backend/app/services/memory.py`, add the function and modify the search method:

```python
import uuid
from datetime import datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Memory
from app.services.llm.base import BaseLLM


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


class MemoryService:
    def __init__(self, session: AsyncSession, llm: BaseLLM):
        self.session = session
        self.llm = llm

    async def write_memory(
        self,
        user_id: uuid.UUID,
        owner_type: str,
        owner_id: uuid.UUID,
        memory_type: str,
        content: str,
        importance_score: float = 0.5,
        emotional_valence: float = 0.0,
        emotional_tags: list[str] | None = None,
        symbolic_tags: list[str] | None = None,
        related_robot_ids: list[uuid.UUID] | None = None,
        summary: str | None = None,
    ) -> Memory:
        embedding = await self.llm.embed(content)

        memory = Memory(
            user_id=user_id,
            owner_type=owner_type,
            owner_id=owner_id,
            memory_type=memory_type,
            content=content,
            summary=summary or content[:100],
            importance_score=importance_score,
            emotional_valence=emotional_valence,
            emotional_tags=emotional_tags or [],
            symbolic_tags=symbolic_tags or [],
            related_robot_ids=related_robot_ids or [],
            embedding=embedding,
        )
        self.session.add(memory)
        await self.session.commit()
        await self.session.refresh(memory)
        return memory

    async def search_memories(
        self,
        query: str,
        user_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        limit: int = 3,
    ) -> list[Memory]:
        query_embedding = await self.llm.embed(query)

        if settings.is_sqlite:
            return await self._search_memories_sqlite(
                query_embedding, user_id, owner_id, limit
            )

        # PostgreSQL path: use pgvector
        stmt = (
            select(Memory)
            .where(Memory.user_id == user_id)
            .where(Memory.embedding.isnot(None))
        )
        if owner_id:
            stmt = stmt.where(Memory.owner_id == owner_id)
        stmt = stmt.order_by(
            Memory.embedding.cosine_distance(query_embedding)
        ).limit(limit)

        result = await self.session.execute(stmt)
        memories = result.scalars().all()

        for memory in memories:
            memory.last_accessed_at = datetime.utcnow()
        await self.session.commit()

        return list(memories)

    async def _search_memories_sqlite(
        self,
        query_embedding: list[float],
        user_id: uuid.UUID,
        owner_id: uuid.UUID | None,
        limit: int,
    ) -> list[Memory]:
        """Fallback vector search: load embeddings, compute cosine similarity in Python."""
        stmt = (
            select(Memory)
            .where(Memory.user_id == user_id)
            .where(Memory.embedding.isnot(None))
        )
        if owner_id:
            stmt = stmt.where(Memory.owner_id == owner_id)

        result = await self.session.execute(stmt)
        all_memories = result.scalars().all()

        scored = []
        for mem in all_memories:
            sim = cosine_similarity(query_embedding, mem.embedding)
            scored.append((sim, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        memories = [mem for _, mem in scored[:limit]]

        for memory in memories:
            memory.last_accessed_at = datetime.utcnow()
        await self.session.commit()

        return memories
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_memory_sqlite.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/memory.py backend/tests/test_memory_sqlite.py
git commit -m "feat(desktop): add numpy cosine similarity fallback for SQLite vector search"
```

---

## Task 3: Backend — SQLite engine and init

**Files:**
- Modify: `backend/app/db/engine.py`
- Create: `backend/app/api/status.py`
- Modify: `backend/app/main.py`

**Context:** The engine needs to work with both PostgreSQL and SQLite. Also add a `/api/status` endpoint for Unity health checks.

- [ ] **Step 1: Update engine.py for SQLite compatibility**

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

connect_args = {}
if settings.is_sqlite:
    connect_args["check_same_thread"] = False

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args=connect_args,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session():
    async with async_session() as session:
        yield session


async def init_db():
    """Create all tables. Used in desktop mode (no Alembic)."""
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 2: Create status endpoint**

Create `backend/app/api/status.py`:

```python
from fastapi import APIRouter

router = APIRouter(tags=["status"])


@router.get("/api/status")
async def status():
    return {
        "status": "ready",
        "mode": "desktop",
        "version": "0.1.0",
    }
```

- [ ] **Step 3: Update main.py to register status route and init SQLite on startup**

In `backend/app/main.py`, add the import and register the router. Update the lifespan to init the database in desktop mode:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.agents import router as agents_router
from app.api.conversations import router as conversations_router
from app.api.objects import router as objects_router
from app.api.robots import router as robots_router
from app.api.tts import router as tts_router
from app.api.stt import router as stt_router
from app.api.heartbeat import router as heartbeat_router
from app.api.regenerate import router as regenerate_router
from app.api.status import router as status_router


async def _prewarm_voices():
    """Pre-register all robots with CosyVoice at startup so first TTS is fast."""
    try:
        from app.db.engine import async_session
        from app.db.models import Robot
        from sqlalchemy import select
        from app.api.tts import _get_or_create_voice, _cosy_register_speaker, _cosy_lock, _cosy_registered

        async with async_session() as session:
            result = await session.execute(select(Robot))
            robots = result.scalars().all()

        print(f"[startup] Pre-warming CosyVoice for {len(robots)} robots...")
        for robot in robots:
            rid = str(robot.id)
            if rid in _cosy_registered:
                continue
            try:
                async with _cosy_lock:
                    if rid in _cosy_registered:
                        continue
                    wav_bytes, prompt_text = await _get_or_create_voice(robot)
                    ok = await _cosy_register_speaker(rid, wav_bytes, prompt_text)
                    print(f"[startup] {robot.name}: {'✓' if ok else '✗'}")
            except Exception as e:
                print(f"[startup] {robot.name} prewarm error: {e}")
        print("[startup] CosyVoice pre-warm complete.")
    except Exception as e:
        print(f"[startup] Pre-warm failed (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_sqlite:
        from app.db.engine import init_db
        await init_db()
        print("[startup] SQLite database initialized.")
    yield


app = FastAPI(title="Nomi", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Desktop mode: allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents_router)
app.include_router(conversations_router)
app.include_router(robots_router)
app.include_router(objects_router)
app.include_router(tts_router)
app.include_router(stt_router)
app.include_router(heartbeat_router)
app.include_router(regenerate_router)
app.include_router(status_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Test manually**

```bash
cd /Users/chao/Documents/Projects/nomi/backend
NOMI_DATABASE_URL="sqlite+aiosqlite:///test_desktop.db" python -m uvicorn app.main:app --port 18900
# In another terminal:
curl http://localhost:18900/api/status
# Expected: {"status":"ready","mode":"desktop","version":"0.1.0"}
curl http://localhost:18900/api/health
# Expected: {"status":"ok"}
```

Clean up test database after verification.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/engine.py backend/app/api/status.py backend/app/main.py
git commit -m "feat(desktop): SQLite auto-init on startup, add /api/status endpoint"
```

---

## Task 4: Backend — Desktop entry point and requirements

**Files:**
- Create: `backend/desktop/entrypoint.py`
- Create: `backend/requirements-desktop.txt`

**Context:** The desktop version needs its own entry point that sets environment variables and launches uvicorn. Also needs a separate requirements file without PostgreSQL/Redis deps.

- [ ] **Step 1: Create desktop entry point**

Create `backend/desktop/entrypoint.py`:

```python
"""
Desktop mode entry point for Nomi backend.
Sets up SQLite database path and launches the FastAPI server.
"""
import os
import sys
from pathlib import Path


def get_data_dir() -> Path:
    """Get platform-specific data directory."""
    if sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support" / "Nomi"
    else:
        data_dir = Path.home() / ".nomi"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def main():
    data_dir = get_data_dir()
    db_path = data_dir / "nomi.db"
    log_dir = data_dir / "logs"
    log_dir.mkdir(exist_ok=True)

    # Set environment for desktop mode
    os.environ["NOMI_DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["NOMI_REDIS_URL"] = ""  # Disable Redis

    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=18900,
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create desktop requirements**

Create `backend/requirements-desktop.txt`:

```
fastapi[standard]==0.115.12
uvicorn[standard]==0.34.2
sqlalchemy[asyncio]==2.0.41
aiosqlite==0.21.0
alembic==1.15.2
pydantic-settings==2.9.1
anthropic==0.52.0
openai==1.82.0
google-genai==1.20.0
httpx==0.28.1
python-multipart==0.0.20
numpy>=1.26.0
```

- [ ] **Step 3: Test desktop entry point**

```bash
cd /Users/chao/Documents/Projects/nomi/backend
python desktop/entrypoint.py &
sleep 3
curl http://127.0.0.1:18900/api/status
# Expected: {"status":"ready","mode":"desktop","version":"0.1.0"}
kill %1
```

- [ ] **Step 4: Commit**

```bash
git add backend/desktop/entrypoint.py backend/requirements-desktop.txt
git commit -m "feat(desktop): add desktop entry point and requirements"
```

---

## Task 5: Backend — PyInstaller packaging

**Files:**
- Create: `backend/desktop/build.py`
- Create: `backend/desktop/nomi-server.spec`

**Context:** Package the entire Python backend into a single macOS executable using PyInstaller.

- [ ] **Step 1: Create PyInstaller spec file**

Create `backend/desktop/nomi-server.spec`:

```python
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
```

- [ ] **Step 2: Create build script**

Create `backend/desktop/build.py`:

```python
"""Build script for packaging Nomi backend with PyInstaller."""
import subprocess
import sys
from pathlib import Path


def main():
    desktop_dir = Path(__file__).parent
    spec_file = desktop_dir / "nomi-server.spec"

    print("Installing desktop dependencies...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-r",
        str(desktop_dir.parent / "requirements-desktop.txt"),
    ])

    print("Installing PyInstaller...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "pyinstaller",
    ])

    print("Building nomi-server...")
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller",
        "--clean",
        str(spec_file),
    ], cwd=str(desktop_dir))

    output = desktop_dir / "dist" / "nomi-server"
    if output.exists():
        print(f"\nBuild successful: {output}")
        print(f"Size: {output.stat().st_size / 1024 / 1024:.1f} MB")
    else:
        print("\nBuild failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Test the build**

```bash
cd /Users/chao/Documents/Projects/nomi/backend
python desktop/build.py
```

Expected: `dist/nomi-server` binary created.

- [ ] **Step 4: Test the built binary**

```bash
cd /Users/chao/Documents/Projects/nomi/backend/desktop
./dist/nomi-server &
sleep 5
curl http://127.0.0.1:18900/api/status
# Expected: {"status":"ready","mode":"desktop","version":"0.1.0"}
kill %1
```

- [ ] **Step 5: Commit**

```bash
git add backend/desktop/build.py backend/desktop/nomi-server.spec
git commit -m "feat(desktop): add PyInstaller build script and spec"
```

---

## Task 6: Unity — Project setup and transparent window

**Files:**
- Create: Unity project `desktop/NomiCompanion/`
- Create: `Assets/Scripts/Core/FloatingWindow.cs`

**Context:** Create the Unity project and set up a transparent, borderless, always-on-top window — the foundation for the desktop companion.

- [ ] **Step 1: Create Unity project**

Open Unity Hub, create a new 2D URP project at `desktop/NomiCompanion/`. Use Unity 2022 LTS or later.

- [ ] **Step 2: Configure Player Settings**

In Unity Editor → Edit → Project Settings → Player:
- Resolution: Default width 200, Default height 300
- Fullscreen Mode: Windowed
- Resizable Window: No
- Run in Background: Yes
- Allow 'scripts only' build: Yes

- [ ] **Step 3: Create FloatingWindow.cs**

Create `Assets/Scripts/Core/FloatingWindow.cs`:

```csharp
using UnityEngine;
using System;
using System.Runtime.InteropServices;

/// <summary>
/// Makes the Unity window transparent, borderless, always-on-top, and draggable.
/// macOS-specific implementation using native Cocoa APIs.
/// </summary>
public class FloatingWindow : MonoBehaviour
{
#if UNITY_STANDALONE_OSX
    [DllImport("__Internal")]
    private static extern IntPtr GetMainWindow();

    // Use Objective-C runtime to configure NSWindow
    [DllImport("libobjc.dylib", EntryPoint = "objc_msgSend")]
    private static extern void objc_msgSend_void_bool(IntPtr receiver, IntPtr selector, bool arg);

    [DllImport("libobjc.dylib", EntryPoint = "objc_msgSend")]
    private static extern void objc_msgSend_void_int(IntPtr receiver, IntPtr selector, int arg);

    [DllImport("libobjc.dylib", EntryPoint = "sel_registerName")]
    private static extern IntPtr sel_registerName(string name);
#endif

    [Header("Window Settings")]
    public int windowWidth = 200;
    public int windowHeight = 300;

    private bool isDragging = false;
    private Vector3 dragOffset;

    void Start()
    {
#if UNITY_STANDALONE_OSX && !UNITY_EDITOR
        SetupTransparentWindow();
#endif
        // Set camera to render transparent background
        Camera.main.clearFlags = CameraClearFlags.SolidColor;
        Camera.main.backgroundColor = new Color(0, 0, 0, 0);
    }

    void SetupTransparentWindow()
    {
#if UNITY_STANDALONE_OSX
        // Configure window via Unity's built-in APIs where possible
        Screen.SetResolution(windowWidth, windowHeight, false);
#endif
    }

    void OnMouseDown()
    {
        isDragging = true;
        dragOffset = Input.mousePosition;
    }

    void OnMouseUp()
    {
        isDragging = false;
    }

    void Update()
    {
        // Handle dragging (move window by dragging the avatar)
        if (isDragging)
        {
            Vector3 currentPos = Input.mousePosition;
            Vector3 diff = currentPos - dragOffset;
            // Window position movement would be handled via native plugin
            dragOffset = currentPos;
        }
    }
}
```

Note: Full transparent window on macOS requires a native Objective-C plugin. The initial version uses Unity's built-in windowing. The native plugin for true transparency will be added in Phase 2.

- [ ] **Step 4: Set up the Main scene**

In Unity Editor:
1. Create an empty GameObject named "AppManager"
2. Attach `FloatingWindow` script to it
3. Set Camera background to solid black with alpha 0
4. Save scene as `Assets/Scenes/Main.unity`

- [ ] **Step 5: Commit Unity project**

```bash
# Add .gitignore for Unity first
cat > desktop/NomiCompanion/.gitignore << 'GITIGNORE'
/[Ll]ibrary/
/[Tt]emp/
/[Oo]bj/
/[Bb]uild/
/[Bb]uilds/
/[Ll]ogs/
/[Uu]ser[Ss]ettings/
*.csproj
*.sln
*.suo
*.tmp
*.user
*.userprefs
*.pidb
*.booproj
*.svd
*.pdb
*.mdb
*.opendb
*.VC.db
*.pidb.meta
*.pdb.meta
*.mdb.meta
GITIGNORE

git add desktop/NomiCompanion/.gitignore desktop/NomiCompanion/Assets/Scripts/Core/FloatingWindow.cs
git commit -m "feat(desktop): Unity project setup with transparent floating window"
```

---

## Task 7: Unity — Backend process manager

**Files:**
- Create: `Assets/Scripts/Core/AppManager.cs`

**Context:** Unity needs to start the Python backend as a subprocess on launch, health-check it, and kill it on exit.

- [ ] **Step 1: Create AppManager.cs**

Create `Assets/Scripts/Core/AppManager.cs`:

```csharp
using UnityEngine;
using UnityEngine.Networking;
using System.Collections;
using System.Diagnostics;
using System.IO;

/// <summary>
/// Manages the app lifecycle: starts backend process, health checks, graceful shutdown.
/// </summary>
public class AppManager : MonoBehaviour
{
    public static AppManager Instance { get; private set; }

    [Header("Backend Settings")]
    public string backendHost = "http://127.0.0.1:18900";
    public float healthCheckInterval = 2f;

    public bool IsBackendReady { get; private set; } = false;

    public delegate void BackendStatusChanged(bool ready);
    public event BackendStatusChanged OnBackendStatusChanged;

    private Process backendProcess;

    void Awake()
    {
        if (Instance != null)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        DontDestroyOnLoad(gameObject);
    }

    void Start()
    {
        StartBackend();
        StartCoroutine(HealthCheckLoop());
    }

    void OnApplicationQuit()
    {
        StopBackend();
    }

    void OnDestroy()
    {
        StopBackend();
    }

    private void StartBackend()
    {
        string serverPath = GetServerPath();
        if (!File.Exists(serverPath))
        {
            UnityEngine.Debug.LogError($"Backend not found at: {serverPath}");
            return;
        }

        UnityEngine.Debug.Log($"Starting backend: {serverPath}");

        backendProcess = new Process();
        backendProcess.StartInfo.FileName = serverPath;
        backendProcess.StartInfo.UseShellExecute = false;
        backendProcess.StartInfo.CreateNoWindow = true;
        backendProcess.StartInfo.RedirectStandardOutput = true;
        backendProcess.StartInfo.RedirectStandardError = true;
        backendProcess.Start();

        UnityEngine.Debug.Log($"Backend started (PID: {backendProcess.Id})");
    }

    private void StopBackend()
    {
        if (backendProcess != null && !backendProcess.HasExited)
        {
            UnityEngine.Debug.Log("Stopping backend...");
            backendProcess.Kill();
            backendProcess.WaitForExit(3000);
            backendProcess.Dispose();
            backendProcess = null;
        }
    }

    private string GetServerPath()
    {
        // In packaged app: Nomi.app/Contents/Resources/backend/nomi-server
        string appPath = Application.dataPath; // .app/Contents/Data in built player
        string resourcesPath = Path.Combine(
            Directory.GetParent(appPath).FullName, "Resources", "backend", "nomi-server"
        );

        // In editor: use dev backend path
#if UNITY_EDITOR
        resourcesPath = Path.Combine(
            Application.dataPath, "..", "..", "..", "backend", "desktop", "dist", "nomi-server"
        );
#endif

        return resourcesPath;
    }

    private IEnumerator HealthCheckLoop()
    {
        while (true)
        {
            yield return new WaitForSeconds(IsBackendReady ? healthCheckInterval : 0.5f);

            using (UnityWebRequest req = UnityWebRequest.Get($"{backendHost}/api/status"))
            {
                req.timeout = 2;
                yield return req.SendWebRequest();

                bool wasReady = IsBackendReady;
                IsBackendReady = req.result == UnityWebRequest.Result.Success;

                if (IsBackendReady != wasReady)
                {
                    UnityEngine.Debug.Log($"Backend status: {(IsBackendReady ? "ready" : "not ready")}");
                    OnBackendStatusChanged?.Invoke(IsBackendReady);
                }
            }
        }
    }
}
```

- [ ] **Step 2: Add to Main scene**

In Unity Editor, attach `AppManager` to the existing "AppManager" GameObject.

- [ ] **Step 3: Commit**

```bash
git add desktop/NomiCompanion/Assets/Scripts/Core/AppManager.cs
git commit -m "feat(desktop): backend process manager with health checking"
```

---

## Task 8: Unity — HTTP client for backend API

**Files:**
- Create: `Assets/Scripts/Core/BackendClient.cs`
- Create: `Assets/Scripts/Models/ApiModels.cs`

**Context:** C# HTTP client to call the FastAPI backend — list robots, send messages, receive responses.

- [ ] **Step 1: Create API data models**

Create `Assets/Scripts/Models/ApiModels.cs`:

```csharp
using System;
using System.Collections.Generic;

/// <summary>
/// C# data classes matching the backend API JSON responses.
/// </summary>
[Serializable]
public class RobotData
{
    public string id;
    public string name;
    public int age;
    public string current_status;
    public string origin_story;
}

[Serializable]
public class RobotListResponse
{
    public List<RobotData> items;
}

[Serializable]
public class MessageData
{
    public string id;
    public string sender_type;
    public string sender_name;
    public string content;
    public string created_at;
}

[Serializable]
public class ConversationResponse
{
    public string id;
    public List<MessageData> messages;
}

[Serializable]
public class SendMessageRequest
{
    public string content;
    public string robot_id;
    public string model;
}

[Serializable]
public class SendMessageResponse
{
    public MessageData user_message;
    public MessageData bot_message;
}

[Serializable]
public class StatusResponse
{
    public string status;
    public string mode;
    public string version;
}
```

- [ ] **Step 2: Create BackendClient**

Create `Assets/Scripts/Core/BackendClient.cs`:

```csharp
using UnityEngine;
using UnityEngine.Networking;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;

/// <summary>
/// HTTP client for communicating with the Python FastAPI backend.
/// </summary>
public class BackendClient : MonoBehaviour
{
    public static BackendClient Instance { get; private set; }

    private string baseUrl;

    void Awake()
    {
        if (Instance != null)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        DontDestroyOnLoad(gameObject);

        baseUrl = AppManager.Instance?.backendHost ?? "http://127.0.0.1:18900";
    }

    /// <summary>List all robots for the default user.</summary>
    public void GetRobots(Action<List<RobotData>> onSuccess, Action<string> onError = null)
    {
        StartCoroutine(GetRequest("/api/robots", (json) =>
        {
            // Backend returns a JSON array directly
            string wrapped = "{\"items\":" + json + "}";
            var response = JsonUtility.FromJson<RobotListResponse>(wrapped);
            onSuccess?.Invoke(response.items);
        }, onError));
    }

    /// <summary>Send a message and get the bot's reply.</summary>
    public void SendMessage(
        string conversationId,
        string content,
        string robotId,
        string model,
        Action<SendMessageResponse> onSuccess,
        Action<string> onError = null)
    {
        var body = new SendMessageRequest
        {
            content = content,
            robot_id = robotId,
            model = model,
        };

        string url = $"/api/conversations/{conversationId}/messages";
        StartCoroutine(PostRequest(url, JsonUtility.ToJson(body), (json) =>
        {
            var response = JsonUtility.FromJson<SendMessageResponse>(json);
            onSuccess?.Invoke(response);
        }, onError));
    }

    /// <summary>Get the latest conversation.</summary>
    public void GetLatestConversation(
        Action<ConversationResponse> onSuccess,
        Action<string> onError = null)
    {
        StartCoroutine(GetRequest("/api/conversations/latest", (json) =>
        {
            if (string.IsNullOrEmpty(json) || json == "null")
            {
                onSuccess?.Invoke(null);
                return;
            }
            var response = JsonUtility.FromJson<ConversationResponse>(json);
            onSuccess?.Invoke(response);
        }, onError));
    }

    private IEnumerator GetRequest(string path, Action<string> onSuccess, Action<string> onError)
    {
        using (UnityWebRequest req = UnityWebRequest.Get(baseUrl + path))
        {
            req.timeout = 30;
            yield return req.SendWebRequest();

            if (req.result == UnityWebRequest.Result.Success)
            {
                onSuccess?.Invoke(req.downloadHandler.text);
            }
            else
            {
                Debug.LogWarning($"GET {path} failed: {req.error}");
                onError?.Invoke(req.error);
            }
        }
    }

    private IEnumerator PostRequest(string path, string jsonBody, Action<string> onSuccess, Action<string> onError)
    {
        using (UnityWebRequest req = new UnityWebRequest(baseUrl + path, "POST"))
        {
            byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonBody);
            req.uploadHandler = new UploadHandlerRaw(bodyRaw);
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = 60; // LLM responses can be slow

            yield return req.SendWebRequest();

            if (req.result == UnityWebRequest.Result.Success)
            {
                onSuccess?.Invoke(req.downloadHandler.text);
            }
            else
            {
                Debug.LogWarning($"POST {path} failed: {req.error}");
                onError?.Invoke(req.error);
            }
        }
    }
}
```

- [ ] **Step 3: Commit**

```bash
git add desktop/NomiCompanion/Assets/Scripts/Models/ApiModels.cs desktop/NomiCompanion/Assets/Scripts/Core/BackendClient.cs
git commit -m "feat(desktop): HTTP client and API data models for backend communication"
```

---

## Task 9: Unity — Avatar display with idle animation

**Files:**
- Create: `Assets/Scripts/UI/AvatarDisplay.cs`

**Context:** Display the robot's avatar as a sprite with simple idle animation (breathing/bobbing effect). This is the always-visible floating character.

- [ ] **Step 1: Create AvatarDisplay.cs**

Create `Assets/Scripts/UI/AvatarDisplay.cs`:

```csharp
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Displays a robot's avatar with simple idle animations.
/// Handles: breathing (scale pulse), gentle bobbing, blink overlay.
/// </summary>
public class AvatarDisplay : MonoBehaviour
{
    [Header("References")]
    public Image avatarImage;
    public Image blinkOverlay; // Semi-transparent eyelid overlay

    [Header("Idle Animation")]
    public float breathSpeed = 1.5f;
    public float breathAmount = 0.02f;
    public float bobSpeed = 0.8f;
    public float bobAmount = 3f;

    [Header("Blink")]
    public float blinkInterval = 4f;
    public float blinkDuration = 0.15f;

    public enum CharacterState { Idle, Listening, Thinking, Speaking }
    public CharacterState State { get; private set; } = CharacterState.Idle;

    private Vector3 baseScale;
    private Vector3 basePosition;
    private float nextBlinkTime;

    void Start()
    {
        baseScale = transform.localScale;
        basePosition = transform.localPosition;
        nextBlinkTime = Time.time + Random.Range(2f, blinkInterval);

        if (blinkOverlay != null)
            blinkOverlay.gameObject.SetActive(false);
    }

    void Update()
    {
        AnimateBreathing();
        AnimateBobbing();
        AnimateBlink();

        // State-specific animations
        switch (State)
        {
            case CharacterState.Thinking:
                AnimateThinking();
                break;
            case CharacterState.Speaking:
                AnimateSpeaking();
                break;
        }
    }

    public void SetState(CharacterState newState)
    {
        State = newState;
    }

    public void SetAvatar(Sprite sprite)
    {
        if (avatarImage != null)
            avatarImage.sprite = sprite;
    }

    private void AnimateBreathing()
    {
        float scale = 1f + Mathf.Sin(Time.time * breathSpeed) * breathAmount;
        transform.localScale = baseScale * scale;
    }

    private void AnimateBobbing()
    {
        float yOffset = Mathf.Sin(Time.time * bobSpeed) * bobAmount;
        transform.localPosition = basePosition + new Vector3(0, yOffset, 0);
    }

    private void AnimateBlink()
    {
        if (blinkOverlay == null) return;

        if (Time.time >= nextBlinkTime)
        {
            blinkOverlay.gameObject.SetActive(true);
            nextBlinkTime = Time.time + blinkDuration;
        }
        else if (blinkOverlay.gameObject.activeSelf &&
                 Time.time >= nextBlinkTime - blinkInterval + blinkDuration)
        {
            blinkOverlay.gameObject.SetActive(false);
            nextBlinkTime = Time.time + Random.Range(blinkInterval * 0.5f, blinkInterval * 1.5f);
        }
    }

    private void AnimateThinking()
    {
        // Gentle head tilt
        float tilt = Mathf.Sin(Time.time * 2f) * 3f;
        transform.localRotation = Quaternion.Euler(0, 0, tilt);
    }

    private void AnimateSpeaking()
    {
        // Rapid small scale pulses to simulate talking
        float pulse = 1f + Mathf.Sin(Time.time * 8f) * 0.01f;
        transform.localScale = baseScale * pulse;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add desktop/NomiCompanion/Assets/Scripts/UI/AvatarDisplay.cs
git commit -m "feat(desktop): avatar display with idle breathing, bobbing, and blink animations"
```

---

## Task 10: Unity — Chat bubble UI

**Files:**
- Create: `Assets/Scripts/UI/ChatBubble.cs`
- Create: `Assets/Scripts/UI/ChatPanel.cs`

**Context:** Chat bubbles appear next to the avatar. Typewriter text effect. Only shows last 2-3 messages, old ones fade out.

- [ ] **Step 1: Create ChatBubble.cs**

Create `Assets/Scripts/UI/ChatBubble.cs`:

```csharp
using UnityEngine;
using UnityEngine.UI;
using System.Collections;
using TMPro;

/// <summary>
/// A single chat bubble that appears next to the character.
/// Supports typewriter text reveal and fade-out.
/// </summary>
public class ChatBubble : MonoBehaviour
{
    [Header("References")]
    public TextMeshProUGUI messageText;
    public Image bubbleBackground;
    public CanvasGroup canvasGroup;

    [Header("Typewriter")]
    public float charsPerSecond = 30f;

    [Header("Colors")]
    public Color userBubbleColor = new Color(0.85f, 0.92f, 1f);
    public Color botBubbleColor = new Color(1f, 1f, 1f);

    private string fullText;
    private bool isRevealing = false;

    public void Setup(string text, bool isUser)
    {
        fullText = text;
        bubbleBackground.color = isUser ? userBubbleColor : botBubbleColor;
        canvasGroup.alpha = 1f;

        if (isUser)
        {
            // User messages appear instantly
            messageText.text = fullText;
        }
        else
        {
            // Bot messages use typewriter effect
            messageText.text = "";
            StartCoroutine(TypewriterReveal());
        }
    }

    private IEnumerator TypewriterReveal()
    {
        isRevealing = true;
        int charIndex = 0;

        while (charIndex < fullText.Length)
        {
            charIndex++;
            messageText.text = fullText.Substring(0, charIndex);
            yield return new WaitForSeconds(1f / charsPerSecond);
        }

        isRevealing = false;
    }

    public void FadeOut(float duration = 0.5f)
    {
        StartCoroutine(FadeOutCoroutine(duration));
    }

    private IEnumerator FadeOutCoroutine(float duration)
    {
        float elapsed = 0;
        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            canvasGroup.alpha = 1f - (elapsed / duration);
            yield return null;
        }
        Destroy(gameObject);
    }

    public void SkipTypewriter()
    {
        if (isRevealing)
        {
            StopAllCoroutines();
            messageText.text = fullText;
            isRevealing = false;
        }
    }
}
```

- [ ] **Step 2: Create ChatPanel.cs**

Create `Assets/Scripts/UI/ChatPanel.cs`:

```csharp
using UnityEngine;
using UnityEngine.UI;
using System.Collections.Generic;
using TMPro;

/// <summary>
/// Manages the chat bubble area next to the avatar.
/// Shows last N messages, fades out old ones.
/// Handles text input and sending messages.
/// </summary>
public class ChatPanel : MonoBehaviour
{
    [Header("References")]
    public Transform bubbleContainer;
    public GameObject chatBubblePrefab;
    public TMP_InputField inputField;
    public Button sendButton;
    public AvatarDisplay avatarDisplay;

    [Header("Settings")]
    public int maxVisibleBubbles = 3;
    public string currentRobotId;
    public string currentConversationId;
    public string chatModel = "deepseek-v4-flash";

    private List<ChatBubble> activeBubbles = new List<ChatBubble>();
    private bool isWaitingForReply = false;

    void Start()
    {
        sendButton.onClick.AddListener(OnSendClicked);
        inputField.onSubmit.AddListener((_) => OnSendClicked());

        // Hide chat panel until backend is ready
        gameObject.SetActive(false);

        if (AppManager.Instance != null)
        {
            AppManager.Instance.OnBackendStatusChanged += OnBackendReady;
        }
    }

    private void OnBackendReady(bool ready)
    {
        if (ready)
        {
            gameObject.SetActive(true);
            LoadRobots();
        }
    }

    private void LoadRobots()
    {
        BackendClient.Instance.GetRobots((robots) =>
        {
            if (robots.Count > 0)
            {
                currentRobotId = robots[0].id;
                Debug.Log($"Selected robot: {robots[0].name}");
            }
        });
    }

    private void OnSendClicked()
    {
        string text = inputField.text.Trim();
        if (string.IsNullOrEmpty(text) || isWaitingForReply) return;

        inputField.text = "";
        AddBubble(text, isUser: true);

        isWaitingForReply = true;
        avatarDisplay?.SetState(AvatarDisplay.CharacterState.Thinking);

        BackendClient.Instance.SendMessage(
            currentConversationId,
            text,
            currentRobotId,
            chatModel,
            onSuccess: (response) =>
            {
                if (currentConversationId == null && response.user_message != null)
                {
                    // Store conversation ID from first message
                }

                AddBubble(response.bot_message.content, isUser: false);
                isWaitingForReply = false;
                avatarDisplay?.SetState(AvatarDisplay.CharacterState.Idle);
            },
            onError: (error) =>
            {
                AddBubble("(连接出错，请稍后再试)", isUser: false);
                isWaitingForReply = false;
                avatarDisplay?.SetState(AvatarDisplay.CharacterState.Idle);
            }
        );
    }

    private void AddBubble(string text, bool isUser)
    {
        // Fade out oldest if at max
        while (activeBubbles.Count >= maxVisibleBubbles)
        {
            var oldest = activeBubbles[0];
            activeBubbles.RemoveAt(0);
            oldest.FadeOut();
        }

        GameObject bubbleObj = Instantiate(chatBubblePrefab, bubbleContainer);
        ChatBubble bubble = bubbleObj.GetComponent<ChatBubble>();
        bubble.Setup(text, isUser);
        activeBubbles.Add(bubble);

        if (!isUser)
        {
            avatarDisplay?.SetState(AvatarDisplay.CharacterState.Speaking);
        }
    }
}
```

- [ ] **Step 3: Commit**

```bash
git add desktop/NomiCompanion/Assets/Scripts/UI/ChatBubble.cs desktop/NomiCompanion/Assets/Scripts/UI/ChatPanel.cs
git commit -m "feat(desktop): chat bubble UI with typewriter effect and message management"
```

---

## Task 11: Unity — macOS tray icon

**Files:**
- Create: `Assets/Scripts/Core/TrayManager.cs`
- Create: `Assets/Plugins/macOS/TrayPlugin.m` (native Objective-C)

**Context:** A macOS menu bar tray icon that allows show/hide, quit, and robot switching.

- [ ] **Step 1: Create native macOS tray plugin**

Create `Assets/Plugins/macOS/TrayPlugin.m`:

```objc
#import <Cocoa/Cocoa.h>

static NSStatusItem *statusItem = nil;

// Callback function pointer for menu actions
typedef void (*MenuCallback)(const char* action);
static MenuCallback menuCallback = NULL;

void TrayPlugin_SetCallback(MenuCallback callback) {
    menuCallback = callback;
}

void TrayPlugin_Create(const char* tooltip) {
    dispatch_async(dispatch_get_main_queue(), ^{
        NSStatusBar *statusBar = [NSStatusBar systemStatusBar];
        statusItem = [statusBar statusItemWithLength:NSSquareStatusItemLength];

        // Use a simple text icon; replace with image later
        statusItem.button.title = @"🤖";
        statusItem.button.toolTip = [NSString stringWithUTF8String:tooltip];

        NSMenu *menu = [[NSMenu alloc] init];

        NSMenuItem *showItem = [[NSMenuItem alloc] initWithTitle:@"显示/隐藏角色"
            action:@selector(menuAction:) keyEquivalent:@""];
        showItem.representedObject = @"toggle";
        showItem.target = statusItem;
        [menu addItem:showItem];

        [menu addItem:[NSMenuItem separatorItem]];

        NSMenuItem *quitItem = [[NSMenuItem alloc] initWithTitle:@"退出 Nomi"
            action:@selector(menuAction:) keyEquivalent:@"q"];
        quitItem.representedObject = @"quit";
        quitItem.target = statusItem;
        [menu addItem:quitItem];

        statusItem.menu = menu;
    });
}

void TrayPlugin_Destroy() {
    dispatch_async(dispatch_get_main_queue(), ^{
        if (statusItem != nil) {
            [[NSStatusBar systemStatusBar] removeStatusItem:statusItem];
            statusItem = nil;
        }
    });
}
```

Note: The native plugin needs to be compiled as a `.bundle` for Unity. This requires Xcode build step:
```bash
clang -framework Cocoa -bundle -o TrayPlugin.bundle TrayPlugin.m
```

- [ ] **Step 2: Create TrayManager.cs**

Create `Assets/Scripts/Core/TrayManager.cs`:

```csharp
using UnityEngine;
using System.Runtime.InteropServices;

/// <summary>
/// Manages the macOS menu bar tray icon.
/// Provides show/hide toggle and quit functionality.
/// </summary>
public class TrayManager : MonoBehaviour
{
#if UNITY_STANDALONE_OSX && !UNITY_EDITOR
    [DllImport("TrayPlugin")]
    private static extern void TrayPlugin_Create(string tooltip);

    [DllImport("TrayPlugin")]
    private static extern void TrayPlugin_Destroy();
#endif

    [Header("References")]
    public GameObject companionRoot; // The main companion UI to show/hide

    private bool isVisible = true;

    void Start()
    {
#if UNITY_STANDALONE_OSX && !UNITY_EDITOR
        TrayPlugin_Create("Nomi Companion");
#endif
    }

    void OnApplicationQuit()
    {
#if UNITY_STANDALONE_OSX && !UNITY_EDITOR
        TrayPlugin_Destroy();
#endif
    }

    /// <summary>Toggle companion visibility.</summary>
    public void ToggleVisibility()
    {
        isVisible = !isVisible;
        if (companionRoot != null)
            companionRoot.SetActive(isVisible);
    }

    /// <summary>Called from native tray menu.</summary>
    public void OnTrayAction(string action)
    {
        switch (action)
        {
            case "toggle":
                ToggleVisibility();
                break;
            case "quit":
                Application.Quit();
                break;
        }
    }
}
```

- [ ] **Step 3: Commit**

```bash
git add desktop/NomiCompanion/Assets/Scripts/Core/TrayManager.cs desktop/NomiCompanion/Assets/Plugins/macOS/TrayPlugin.m
git commit -m "feat(desktop): macOS tray icon with show/hide and quit menu"
```

---

## Task 12: Integration — Scene assembly and build

**Context:** Wire everything together in the Unity scene and create a build.

- [ ] **Step 1: Assemble the Main scene**

In Unity Editor, set up the scene hierarchy:

```
Main Camera (with transparent background)
AppManager
  - AppManager.cs
  - BackendClient.cs
  - TrayManager.cs
CompanionRoot
  AvatarDisplay
    - AvatarDisplay.cs
    - Image (avatar sprite)
    - Image (blink overlay, initially hidden)
  ChatPanel
    - ChatPanel.cs
    BubbleContainer (Vertical Layout Group)
    InputArea
      - TMP_InputField
      - Send Button
```

Configure references:
- `TrayManager.companionRoot` → CompanionRoot
- `ChatPanel.avatarDisplay` → AvatarDisplay
- `ChatPanel.chatBubblePrefab` → ChatBubble prefab

- [ ] **Step 2: Create ChatBubble prefab**

In Unity Editor:
1. Create a UI Panel with `ChatBubble.cs`, `CanvasGroup`
2. Add child: `Image` (bubble background, rounded corners)
3. Add child: `TextMeshPro - Text` (message text)
4. Save as prefab at `Assets/Resources/Prefabs/ChatBubble.prefab`

- [ ] **Step 3: Build the Unity app**

In Unity Editor:
1. File → Build Settings
2. Target: macOS
3. Architecture: Apple Silicon
4. Build to `desktop/build/Nomi.app`

- [ ] **Step 4: Copy backend binary into app bundle**

```bash
mkdir -p desktop/build/Nomi.app/Contents/Resources/backend
cp backend/desktop/dist/nomi-server desktop/build/Nomi.app/Contents/Resources/backend/
```

- [ ] **Step 5: Test the complete app**

```bash
open desktop/build/Nomi.app
```

Verify:
- App launches
- Backend starts (check `curl http://127.0.0.1:18900/api/status`)
- Avatar appears on screen
- Tray icon visible in menu bar
- Can type and send a message
- Bot responds with a chat bubble

- [ ] **Step 6: Commit**

```bash
git add desktop/NomiCompanion/Assets/Scenes/ desktop/NomiCompanion/Assets/Resources/
git commit -m "feat(desktop): complete Phase 1 scene assembly and build config"
```
