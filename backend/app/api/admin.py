"""Admin panel API for character management."""
import base64
import json
import os
import shutil
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import async_session, get_session
from app.db.models import AssetVersion, Robot, YearlyMemory

router = APIRouter(prefix="/api/admin", tags=["admin"])

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "desktop", "assets")
CHARACTERS_DIR = os.path.join(ASSETS_DIR, "characters")
VOICES_DIR = os.path.join(ASSETS_DIR, "voices")
GEMINI_API_KEY = settings.gemini_api_key

DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

STATES = ["idle", "thinking", "speaking", "listening", "happy", "sad", "surprised"]


@router.get("/characters")
async def list_characters():
    """List all characters with their assets info."""
    async with async_session() as session:
        result = await session.execute(select(Robot).where(Robot.user_id == DEFAULT_USER_ID))
        robots = result.scalars().all()

        # Get memory counts per robot
        memory_counts = {}
        for r in robots:
            mem_result = await session.execute(
                select(func.count(YearlyMemory.id))
                .where(YearlyMemory.robot_id == r.id)
            )
            memory_counts[r.id] = mem_result.scalar() or 0

    chars = []
    for r in robots:
        char_dir = _get_char_dir(r.name)
        voice_dir = _get_voice_dir(r.name)
        prompts_file = os.path.join(char_dir, "prompts.json") if char_dir else None

        prompts = {}
        if prompts_file and os.path.exists(prompts_file):
            with open(prompts_file) as f:
                prompts = json.load(f)

        states_status = {}
        if char_dir and os.path.exists(char_dir):
            for s in STATES:
                states_status[s] = os.path.exists(os.path.join(char_dir, f"{s}.png"))

        has_voice = False
        if voice_dir and os.path.exists(voice_dir):
            has_voice = any(f.endswith(".wav") for f in os.listdir(voice_dir))

        chars.append({
            "id": str(r.id),
            "name": r.name,
            "age": r.age,
            "birth_place": r.birth_place,
            "system_prompt": r.system_prompt,
            "personality": r.personality,
            "speaking_style": r.speaking_style,
            "origin_story": r.origin_story,
            "voice_profile": r.voice_profile,
            "portrait": r.portrait,
            "generation_stats": r.generation_stats,
            "core_desire": r.core_desire,
            "core_fear": r.core_fear,
            "char_dir": char_dir,
            "states": states_status,
            "prompts": prompts,
            "has_voice": has_voice,
            "memory_count": memory_counts.get(r.id, 0),
            "desktop_visible": r.desktop_visible,
        })

    return chars


@router.post("/characters/{char_id}/voice-lang")
async def set_voice_lang(char_id: str, body: dict):
    """Set the TTS output language for a character."""
    async with async_session() as session:
        result = await session.execute(select(Robot).where(Robot.id == uuid.UUID(char_id)))
        robot = result.scalar_one_or_none()
        if not robot:
            return JSONResponse({"error": "Not found"}, status_code=404)
        vp = dict(robot.voice_profile or {})
        vp["tts_lang"] = body.get("tts_lang", "zh")
        robot.voice_profile = vp
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(robot, "voice_profile")
        await session.commit()
        return {"ok": True, "tts_lang": vp["tts_lang"]}


@router.post("/characters/{char_id}/generate-images")
async def generate_images(
    char_id: str,
    base_prompt: str = Form(...),
    state_prompts: str = Form(...),  # JSON string: {"idle": "...", "thinking": "..."}
):
    """Generate character state images using Gemini Imagen."""
    async with async_session() as session:
        result = await session.execute(select(Robot).where(Robot.id == uuid.UUID(char_id)))
        robot = result.scalar_one_or_none()
        if not robot:
            return JSONResponse({"error": "Robot not found"}, status_code=404)

    char_dir = _get_char_dir(robot.name)
    os.makedirs(char_dir, exist_ok=True)

    prompts_dict = json.loads(state_prompts)
    results = {}

    versions_dir = os.path.join(char_dir, "versions")
    os.makedirs(versions_dir, exist_ok=True)

    import urllib.request
    for state, prompt in prompts_dict.items():
        full_prompt = f"{base_prompt} {prompt}"
        try:
            img_data = _call_imagen(full_prompt)
            if img_data:
                path = os.path.join(char_dir, f"{state}.png")

                # Archive old file if it exists
                if os.path.exists(path):
                    # Find current version number for archiving
                    async with async_session() as session:
                        ver_result = await session.execute(
                            select(func.coalesce(func.max(AssetVersion.version_number), 0))
                            .where(AssetVersion.robot_id == robot.id)
                            .where(AssetVersion.asset_type == "image")
                            .where(AssetVersion.asset_key == state)
                        )
                        current_max = ver_result.scalar()
                    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    archive_name = f"{state}_v{current_max}_{timestamp}.png"
                    archive_path = os.path.join(versions_dir, archive_name)
                    shutil.move(path, archive_path)
                    # Save version record for the archived file
                    if current_max > 0:
                        pass  # Already has a record
                    else:
                        await _save_version(robot.id, "image", state, archive_path,
                                            {"prompt": prompt, "archived": True})

                # Write new file
                with open(path, "wb") as f:
                    f.write(img_data)

                # Create version record for the new file
                ver_num = await _save_version(robot.id, "image", state, path,
                                              {"prompt": full_prompt, "base_prompt": base_prompt})
                results[state] = {"ok": True, "size": len(img_data), "version": ver_num}
            else:
                results[state] = {"ok": False, "error": "No image returned"}
        except Exception as e:
            results[state] = {"ok": False, "error": str(e)}

    # Save prompts
    prompts_data = {
        "base_prompt": base_prompt,
        "states": {s: {"prompt": p} for s, p in prompts_dict.items()},
    }
    with open(os.path.join(char_dir, "prompts.json"), "w") as f:
        json.dump(prompts_data, f, ensure_ascii=False, indent=2)

    return {"results": results}


@router.post("/characters/{char_id}/remove-bg")
async def remove_backgrounds(char_id: str):
    """Remove white backgrounds from character images."""
    async with async_session() as session:
        result = await session.execute(select(Robot).where(Robot.id == uuid.UUID(char_id)))
        robot = result.scalar_one_or_none()
        if not robot:
            return JSONResponse({"error": "Robot not found"}, status_code=404)

    char_dir = _get_char_dir(robot.name)
    if not char_dir or not os.path.exists(char_dir):
        return JSONResponse({"error": "No character directory"}, status_code=404)

    try:
        from rembg import remove
        from PIL import Image
        import numpy as np

        processed = []
        for state in STATES:
            path = os.path.join(char_dir, f"{state}.png")
            if not os.path.exists(path):
                continue
            img = Image.open(path)
            out = remove(img)
            # Crop to content bounds
            arr = np.array(out)
            alpha = arr[:, :, 3]
            rows = np.any(alpha > 0, axis=1)
            cols = np.any(alpha > 0, axis=0)
            if rows.any() and cols.any():
                rmin, rmax = np.where(rows)[0][[0, -1]]
                cmin, cmax = np.where(cols)[0][[0, -1]]
                pad = 5
                arr = arr[max(0, rmin - pad):rmax + pad + 1, max(0, cmin - pad):cmax + pad + 1]
            Image.fromarray(arr).save(path)
            processed.append(state)

        return {"processed": processed}
    except ImportError as e:
        return JSONResponse({"error": f"Missing dependency: {e}"}, status_code=500)


@router.post("/characters/{char_id}/upload-voice")
async def upload_voice(
    char_id: str,
    audio: UploadFile = File(...),
):
    """Upload a reference voice audio file for a character."""
    async with async_session() as session:
        result = await session.execute(select(Robot).where(Robot.id == uuid.UUID(char_id)))
        robot = result.scalar_one_or_none()
        if not robot:
            return JSONResponse({"error": "Robot not found"}, status_code=404)

    voice_dir = _get_voice_dir(robot.name)
    os.makedirs(voice_dir, exist_ok=True)

    content = await audio.read()
    filename = "voice1.wav"
    path = os.path.join(voice_dir, filename)

    # Convert to wav if needed
    if audio.filename and not audio.filename.endswith(".wav"):
        tmp_path = os.path.join(voice_dir, audio.filename)
        with open(tmp_path, "wb") as f:
            f.write(content)
        os.system(f'ffmpeg -y -i "{tmp_path}" -ar 32000 -ac 1 -t 5 "{path}" 2>/dev/null')
        os.unlink(tmp_path)
    else:
        with open(path, "wb") as f:
            f.write(content)

    return {"saved": path, "size": os.path.getsize(path)}


@router.post("/characters/{char_id}/upload-reference")
async def upload_reference(
    char_id: str,
    image: UploadFile = File(...),
):
    """Upload a reference image for character generation."""
    async with async_session() as session:
        result = await session.execute(select(Robot).where(Robot.id == uuid.UUID(char_id)))
        robot = result.scalar_one_or_none()
        if not robot:
            return JSONResponse({"error": "Robot not found"}, status_code=404)

    char_dir = _get_char_dir(robot.name)
    os.makedirs(char_dir, exist_ok=True)

    content = await image.read()
    ref_path = os.path.join(char_dir, "reference.png")
    with open(ref_path, "wb") as f:
        f.write(content)

    return {"saved": ref_path, "size": len(content)}


@router.post("/characters/create")
async def create_character(
    name: str = Form(...),
    origin_story: str = Form(""),
    personality: str = Form("[]"),
    system_prompt: str = Form(""),
    dir_name: str = Form(""),
):
    """Create a new character in the database."""
    async with async_session() as session:
        existing = await session.execute(select(Robot).where(Robot.name == name))
        if existing.scalar_one_or_none():
            return JSONResponse({"error": f"Character '{name}' already exists"}, status_code=400)

        robot = Robot(
            id=uuid.uuid4(),
            user_id=DEFAULT_USER_ID,
            name=name,
            origin_story=origin_story,
            personality=json.loads(personality) if personality else {},
            system_prompt=system_prompt,
        )
        session.add(robot)
        await session.commit()

        # Create directories
        d = dir_name or name.lower().replace(" ", "")
        os.makedirs(os.path.join(CHARACTERS_DIR, d), exist_ok=True)
        os.makedirs(os.path.join(VOICES_DIR, d), exist_ok=True)

        return {"id": str(robot.id), "name": robot.name}


@router.get("/characters/{char_id}/image/{state}")
async def get_character_image(char_id: str, state: str):
    """Get a character state image."""
    async with async_session() as session:
        result = await session.execute(select(Robot).where(Robot.id == uuid.UUID(char_id)))
        robot = result.scalar_one_or_none()
        if not robot:
            return JSONResponse({"error": "Not found"}, status_code=404)

    char_dir = _get_char_dir(robot.name)
    path = os.path.join(char_dir, f"{state}.png") if char_dir else None
    if not path or not os.path.exists(path):
        # Return a placeholder SVG instead of 404
        name_char = robot.name[0] if robot.name else "?"
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><rect fill="#2a2a4a" width="200" height="200" rx="24"/><text x="100" y="120" fill="#666" text-anchor="middle" font-size="72">{name_char}</text></svg>'
        from fastapi.responses import Response as Resp
        return Resp(content=svg.encode(), media_type="image/svg+xml")

    with open(path, "rb") as f:
        data = f.read()

    from fastapi.responses import Response
    return Response(content=data, media_type="image/png")


@router.get("/characters/{char_id}/voice-ref")
async def get_voice_ref(char_id: str):
    """Get the reference audio used for voice cloning."""
    async with async_session() as session:
        result = await session.execute(select(Robot).where(Robot.id == uuid.UUID(char_id)))
        robot = result.scalar_one_or_none()
        if not robot:
            return JSONResponse({"error": "Not found"}, status_code=404)

    voice_dir = _get_voice_dir(robot.name)
    path = os.path.join(voice_dir, "voice_ref.wav")
    if not os.path.exists(path):
        return JSONResponse({"error": "No reference audio"}, status_code=404)

    with open(path, "rb") as f:
        data = f.read()

    from fastapi.responses import Response
    return Response(content=data, media_type="audio/wav")


# ---- Helpers ----

_CHAR_DIR_MAP = {
    "フリーレン": "frieren",
    "冯宝宝": "fengbaobao",
    "禰豆子": "nezuko",
}

def _get_char_dir(name: str) -> str:
    d = _CHAR_DIR_MAP.get(name, name.lower().replace(" ", ""))
    return os.path.join(CHARACTERS_DIR, d)

def _get_voice_dir(name: str) -> str:
    d = _CHAR_DIR_MAP.get(name, name.lower().replace(" ", ""))
    return os.path.join(VOICES_DIR, d)

def _call_imagen(prompt: str) -> bytes | None:
    import urllib.request
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {"sampleCount": 1, "aspectRatio": "1:1", "outputOptions": {"mimeType": "image/png"}},
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
    predictions = data.get("predictions", [])
    if predictions:
        return base64.b64decode(predictions[0]["bytesBase64Encoded"])
    return None


async def _save_version(robot_id: uuid.UUID, asset_type: str, asset_key: str,
                        file_path: str, metadata: dict | None = None):
    """Save a new version record and return the version number."""
    async with async_session() as session:
        result = await session.execute(
            select(func.coalesce(func.max(AssetVersion.version_number), 0))
            .where(AssetVersion.robot_id == robot_id)
            .where(AssetVersion.asset_type == asset_type)
            .where(AssetVersion.asset_key == asset_key)
        )
        next_version = result.scalar() + 1

        await session.execute(
            update(AssetVersion)
            .where(AssetVersion.robot_id == robot_id)
            .where(AssetVersion.asset_type == asset_type)
            .where(AssetVersion.asset_key == asset_key)
            .values(is_current=False)
        )

        version = AssetVersion(
            id=uuid.uuid4(),
            robot_id=robot_id,
            asset_type=asset_type,
            asset_key=asset_key,
            version_number=next_version,
            file_path=file_path,
            metadata_=metadata,
            is_current=True,
        )
        session.add(version)
        await session.commit()
        return next_version


# ---- Version Management Endpoints ----

@router.get("/characters/{char_id}/versions")
async def list_versions(char_id: str, asset_type: str = "image", asset_key: str = ""):
    """List all versions of a specific asset."""
    async with async_session() as session:
        query = (
            select(AssetVersion)
            .where(AssetVersion.robot_id == uuid.UUID(char_id))
            .where(AssetVersion.asset_type == asset_type)
        )
        if asset_key:
            query = query.where(AssetVersion.asset_key == asset_key)
        query = query.order_by(AssetVersion.version_number.desc())

        result = await session.execute(query)
        versions = result.scalars().all()

    return [
        {
            "id": str(v.id),
            "asset_type": v.asset_type,
            "asset_key": v.asset_key,
            "version_number": v.version_number,
            "file_path": v.file_path,
            "metadata": v.metadata_,
            "is_current": v.is_current,
            "is_starred": v.is_starred,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]


@router.post("/characters/{char_id}/versions/{version_id}/activate")
async def activate_version(char_id: str, version_id: str):
    """Switch to a specific version - copy version file to current position."""
    async with async_session() as session:
        result = await session.execute(
            select(AssetVersion).where(AssetVersion.id == uuid.UUID(version_id))
        )
        version = result.scalar_one_or_none()
        if not version:
            return JSONResponse({"error": "Version not found"}, status_code=404)

        robot_result = await session.execute(
            select(Robot).where(Robot.id == uuid.UUID(char_id))
        )
        robot = robot_result.scalar_one_or_none()
        if not robot:
            return JSONResponse({"error": "Robot not found"}, status_code=404)

        # Copy version file to current position
        char_dir = _get_char_dir(robot.name)
        current_path = os.path.join(char_dir, f"{version.asset_key}.png")
        if version.file_path and os.path.exists(version.file_path):
            shutil.copy2(version.file_path, current_path)

        # Update is_current flags
        await session.execute(
            update(AssetVersion)
            .where(AssetVersion.robot_id == version.robot_id)
            .where(AssetVersion.asset_type == version.asset_type)
            .where(AssetVersion.asset_key == version.asset_key)
            .values(is_current=False)
        )
        version.is_current = True
        await session.commit()

    return {"activated": version_id, "asset_key": version.asset_key}


@router.post("/characters/{char_id}/versions/{version_id}/star")
async def toggle_star(char_id: str, version_id: str):
    """Toggle star on a version."""
    async with async_session() as session:
        result = await session.execute(
            select(AssetVersion).where(AssetVersion.id == uuid.UUID(version_id))
        )
        version = result.scalar_one_or_none()
        if not version:
            return JSONResponse({"error": "Version not found"}, status_code=404)

        version.is_starred = not version.is_starred
        await session.commit()

    return {"id": str(version.id), "is_starred": version.is_starred}


@router.get("/characters/{char_id}/versions/{version_id}/file")
async def get_version_file(char_id: str, version_id: str):
    """Serve a version's image file."""
    async with async_session() as session:
        result = await session.execute(
            select(AssetVersion).where(AssetVersion.id == uuid.UUID(version_id))
        )
        version = result.scalar_one_or_none()
        if not version:
            return JSONResponse({"error": "Version not found"}, status_code=404)

    if not version.file_path or not os.path.exists(version.file_path):
        return JSONResponse({"error": "File not found"}, status_code=404)

    with open(version.file_path, "rb") as f:
        data = f.read()

    from fastapi.responses import Response
    return Response(content=data, media_type="image/png")


@router.get("/characters/{char_id}/memories")
async def list_memories(char_id: str):
    """Get all yearly memories for a character, ordered by age."""
    async with async_session() as session:
        result = await session.execute(
            select(YearlyMemory)
            .where(YearlyMemory.robot_id == uuid.UUID(char_id))
            .order_by(YearlyMemory.age)
        )
        memories = result.scalars().all()

    return [
        {
            "id": str(m.id),
            "age": m.age,
            "title": m.memory_title,
            "content": m.memory_content,
            "memory_type": m.memory_type,
            "importance": m.importance,
            "strength": m.memory_strength,
            "emotional_impact": m.emotional_impact,
            "symbolic_tags": m.symbolic_tags,
        }
        for m in memories
    ]


@router.get("/tools")
async def list_tool_settings():
    """All registered tools with their enabled state."""
    import app.services.tools  # noqa: F401 — ensure registration
    from app.services.tools.registry import all_tools, is_enabled
    return [
        {"name": t.name, "display_name": t.display_name,
         "description": t.description, "enabled": is_enabled(t.name)}
        for t in all_tools()
    ]


@router.put("/tools/{tool_name}")
async def update_tool_setting(tool_name: str, body: dict, session: AsyncSession = Depends(get_session)):
    import app.services.tools  # noqa: F401
    from app.services.tools.registry import get_tool
    from app.services.tools.toggles import set_tool_enabled
    if not get_tool(tool_name):
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    enabled = bool(body.get("enabled", True))
    await set_tool_enabled(session, tool_name, enabled)
    return {"name": tool_name, "enabled": enabled}
