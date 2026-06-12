from pathlib import Path

from pydantic_settings import BaseSettings

# 仓库根目录的 .env（backend/app/config.py 上溯三级）。进程环境变量优先于该文件。
_ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://nomi:nomi@localhost:5432/nomi?ssl=disable"
    redis_url: str = "redis://localhost:6380/0"
    llm_provider: str = "claude-cli"  # "claude-cli", "anthropic", or "openai"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    amap_api_key: str = ""       # 高德开放平台 Web 服务 Key
    default_city: str = "北京"    # 工具技能的默认城市（用户聊天中提到地点时覆盖）
    timezone: str = "Asia/Shanghai"  # 提醒/时间解析时区
    embedding_dimensions: int = 768
    cors_origins: list[str] = ["http://localhost:3100", "https://nomi.zhuchao.life", "https://nomi-api.zhuchao.life"]

    model_config = {
        "env_prefix": "NOMI_",
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url


settings = Settings()
