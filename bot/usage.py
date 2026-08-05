"""Счётчик транзакций и токенов — append-only JSONL, без отдельной БД.

Каждая обработанная (успешно или с ошибкой) LLM-транзакция дописывается одной
строкой в USAGE_FILE. Для объёма этого бота (горстка партнёров, не непрерывный
поток) читать файл целиком на /stats дешевле, чем заводить БД ради счётчика.
"""
import json
import logging
import time
from pathlib import Path
from typing import Any

import config

log = logging.getLogger(__name__)


# Цены OpenAI за 1M токенов (проверено на platform.openai.com). Кэшированный вход
# дешевле обычного на порядок, поэтому считается отдельной ставкой — без этого
# оценка стоимости завышена в разы (у нас из кэша приходит большая часть входа).
PRICES_PER_1M = {
    "gpt-5.6-luna": {"in": 0.20, "cached_in": 0.02, "out": 1.20},
    "gpt-5.6-terra": {"in": 2.00, "cached_in": 0.20, "out": 12.00},
    "gpt-5.6-sol": {"in": 5.00, "cached_in": 0.50, "out": 30.00},
    "gpt-4o-mini": {"in": 0.15, "cached_in": 0.075, "out": 0.60},
}


def estimate_cost(model: str, prompt_tokens: int, cached_prompt_tokens: int, completion_tokens: int) -> float:
    """Стоимость запроса в долларах. Неизвестная модель -> 0.0: лучше показать
    ноль, чем посчитать по цене чужой модели и ввести в заблуждение."""
    p = PRICES_PER_1M.get(model)
    if not p:
        return 0.0
    fresh = max(prompt_tokens - cached_prompt_tokens, 0)
    return (fresh * p["in"] + cached_prompt_tokens * p["cached_in"] + completion_tokens * p["out"]) / 1e6


def record(
    *,
    telegram_id: int,
    user_name: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    rounds: int,
    ok: bool,
    cached_prompt_tokens: int = 0,
) -> None:
    entry = {
        "ts": time.time(),
        "telegram_id": telegram_id,
        "user_name": user_name,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "cached_prompt_tokens": cached_prompt_tokens,
        "cost_usd": round(estimate_cost(model, prompt_tokens, cached_prompt_tokens, completion_tokens), 6),
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "rounds": rounds,
        "ok": ok,
    }
    path = Path(config.USAGE_FILE)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        # Учёт — вспомогательная штука, её сбой не должен ронять ответ партнёру.
        log.exception("Не удалось записать usage-лог")


def summarize() -> dict[str, Any]:
    path = Path(config.USAGE_FILE)
    if not path.exists():
        return {"transactions": 0, "failed": 0, "total_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0, "by_user": {}}

    transactions = 0
    failed = 0
    total_tokens = 0
    cached_tokens = 0
    cost_usd = 0.0
    by_user: dict[str, dict[str, float]] = {}

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            transactions += 1
            total_tokens += entry.get("total_tokens", 0)
            cached_tokens += entry.get("cached_prompt_tokens", 0)
            # В старых записях cost_usd нет — досчитываем на месте, чтобы
            # история не занижала сумму.
            entry_cost = entry.get("cost_usd")
            if entry_cost is None:
                entry_cost = estimate_cost(
                    entry.get("model", ""),
                    entry.get("prompt_tokens", 0),
                    entry.get("cached_prompt_tokens", 0),
                    entry.get("completion_tokens", 0),
                )
            cost_usd += entry_cost
            if not entry.get("ok", True):
                failed += 1
            key = str(entry.get("user_name", "?"))
            stat = by_user.setdefault(key, {"transactions": 0, "total_tokens": 0, "cost_usd": 0.0})
            stat["transactions"] += 1
            stat["total_tokens"] += entry.get("total_tokens", 0)
            stat["cost_usd"] += entry_cost

    return {
        "transactions": transactions,
        "failed": failed,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": cost_usd,
        "by_user": by_user,
    }
