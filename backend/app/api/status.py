from fastapi import APIRouter

router = APIRouter(tags=["status"])


@router.get("/api/status")
async def status():
    return {
        "status": "ready",
        "mode": "desktop",
        "version": "0.1.0",
    }
