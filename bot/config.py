"""Конфигурация из переменных окружения (.env через docker-compose)."""
import os


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} не задан — впиши его в .env")
    return value


BOT_TOKEN = _require("BOT_TOKEN")

OPENAI_API_KEY = _require("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")

# Read-only соединение с MCP Базы Знаний: без заголовка Mcp-Mode сервер отдаёт
# только read-инструменты (см. bot/mcp_client.py).
KB_MCP_URL = os.environ.get("KB_MCP_URL", "https://knowledgebase.dodois.io/mcp")
KB_MCP_TOKEN = _require("KB_MCP_TOKEN")

# Счётчик транзакций/токенов — append-only JSONL, каталог живёт в отдельном Docker-volume.
USAGE_FILE = os.environ.get("USAGE_FILE", "/app/data/usage.jsonl")

# Кому отвечает /stats. Не задан — команда молчит для всех (безопасный дефолт).
_admin_id = os.environ.get("ADMIN_TELEGRAM_ID")
ADMIN_TELEGRAM_ID = int(_admin_id) if _admin_id else None
