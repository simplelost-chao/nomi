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
from app.api.tts_genie import router as tts_genie_router
from app.api.admin import router as admin_router
from app.api.admin_web_creation import router as admin_web_creation_router


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
    from app.services.tools.toggles import hydrate_tool_settings
    await hydrate_tool_settings()
    import asyncio
    from app.services.reminders import reminders_loop
    reminder_task = asyncio.create_task(reminders_loop())
    yield
    reminder_task.cancel()


app = FastAPI(title="Nomi", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
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
app.include_router(tts_genie_router)
app.include_router(admin_router)
app.include_router(admin_web_creation_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/admin")
async def admin_page():
    """Serve the admin panel HTML."""
    import os
    from fastapi.responses import HTMLResponse
    html_path = os.path.join(os.path.dirname(__file__), "admin_panel.html")
    with open(html_path, "r") as f:
        return HTMLResponse(f.read(), headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"})
