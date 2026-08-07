"""Общая настройка тестов.

Модули бота читают конфигурацию из окружения на импорте (config._require), поэтому
переменные выставляем до импорта — иначе любой тест падал бы на отсутствии токенов.
Значения фиктивные: тесты покрывают только чистые функции и наружу не ходят.
"""
import pathlib
import sys

BOT_DIR = pathlib.Path(__file__).resolve().parent.parent / "bot"
sys.path.insert(0, str(BOT_DIR))

import os  # noqa: E402

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("KB_MCP_TOKEN", "test-kb-token")
os.environ.setdefault("USAGE_FILE", "/tmp/dodo_kb_bot_test_usage.jsonl")
