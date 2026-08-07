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


def _int_set(name: str) -> frozenset[int]:
    raw = os.environ.get(name, "")
    return frozenset(int(p) for p in raw.replace(",", " ").split() if p.strip())


# Чаты, в которых боту разрешено отвечать (id через запятую). Пусто — отвечает в
# любом чате, куда его добавили; тогда единственная граница доступа к Базе
# Знаний — кто именно добавляет бота. Список стоит задать, если бот может
# оказаться в чужом чате.
ALLOWED_CHAT_IDS = _int_set("ALLOWED_CHAT_IDS")

# Ограничение частоты: защита от случайного и намеренного спама вопросами —
# каждый вопрос это несколько вызовов LLM, то есть реальные деньги и минуты
# работы. Пауза между вопросами одного пользователя и потолок на чат в час.
USER_COOLDOWN_SECONDS = int(os.environ.get("USER_COOLDOWN_SECONDS", "10"))
CHAT_HOURLY_LIMIT = int(os.environ.get("CHAT_HOURLY_LIMIT", "60"))
