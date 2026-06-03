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

    # Ensure backend package is importable
    backend_dir = Path(__file__).resolve().parent.parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    os.chdir(backend_dir)

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
