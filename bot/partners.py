"""Единственная точка доступа: список партнёров, которым разрешено писать боту.

Токен от Базы Знаний партнёрам никогда не выдаётся — бот сам ходит в MCP от имени
одного сервисного PAT (config.KB_MCP_TOKEN). Этот файл — не про доступ к KB (он
read-only для всех), а про то, кому вообще разрешено разговаривать с ботом.
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import config

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Partner:
    telegram_id: int
    name: str
    country: str


_partners: dict[int, Partner] | None = None


def _load() -> dict[int, Partner]:
    global _partners
    if _partners is not None:
        return _partners

    path = Path(config.PARTNERS_FILE)
    if not path.exists():
        log.warning("Файл партнёров %s не найден — доступ закрыт всем", path)
        _partners = {}
        return _partners

    raw = json.loads(path.read_text(encoding="utf-8"))
    loaded = {
        int(entry["telegram_id"]): Partner(
            telegram_id=int(entry["telegram_id"]),
            name=entry["name"],
            country=entry["country"],
        )
        for entry in raw
    }
    log.info("Загружено партнёров: %d", len(loaded))
    _partners = loaded
    return _partners


def get_partner(telegram_id: int) -> Partner | None:
    return _load().get(telegram_id)


def reload() -> None:
    """Сбрасывает кэш — следующий get_partner перечитает файл с диска."""
    global _partners
    _partners = None
