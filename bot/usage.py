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


def record(
    *,
    telegram_id: int,
    partner_name: str,
    country: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    rounds: int,
    ok: bool,
) -> None:
    entry = {
        "ts": time.time(),
        "telegram_id": telegram_id,
        "partner_name": partner_name,
        "country": country,
        "model": model,
        "prompt_tokens": prompt_tokens,
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
        return {"transactions": 0, "failed": 0, "total_tokens": 0, "by_partner": {}}

    transactions = 0
    failed = 0
    total_tokens = 0
    by_partner: dict[str, dict[str, int]] = {}

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
            if not entry.get("ok", True):
                failed += 1
            key = f"{entry.get('partner_name', '?')} ({entry.get('country', '?')})"
            stat = by_partner.setdefault(key, {"transactions": 0, "total_tokens": 0})
            stat["transactions"] += 1
            stat["total_tokens"] += entry.get("total_tokens", 0)

    return {
        "transactions": transactions,
        "failed": failed,
        "total_tokens": total_tokens,
        "by_partner": by_partner,
    }
