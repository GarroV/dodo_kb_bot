"""Кто и как часто может занимать бота.

Два независимых ограничителя, оба нужны по одной причине: каждый вопрос — это
несколько вызовов LLM и обращений к Базе Знаний, то есть деньги и десятки секунд
работы. Без них любой участник чата может случайно (зажатый Enter) или намеренно
сжечь бюджет.

Состояние держится в памяти процесса: перезапуск контейнера его обнуляет, и это
осознанно — ради ограничения частоты не нужна ни база, ни файл, а бот
перезапускается редко.
"""
import time
from collections import defaultdict, deque

import config


class Throttle:
    """Пауза между вопросами одного пользователя + потолок вопросов на чат в час."""

    def __init__(
        self,
        user_cooldown_seconds: int | None = None,
        chat_hourly_limit: int | None = None,
        now: object = None,
    ) -> None:
        self._cooldown = (
            config.USER_COOLDOWN_SECONDS if user_cooldown_seconds is None else user_cooldown_seconds
        )
        self._hourly = config.CHAT_HOURLY_LIMIT if chat_hourly_limit is None else chat_hourly_limit
        # now вынесен параметром, чтобы тесты не зависели от реального времени.
        self._now = now or time.monotonic
        self._last_by_user: dict[int, float] = {}
        self._chat_hits: dict[int, deque[float]] = defaultdict(deque)

    def check(self, user_id: int, chat_id: int) -> str | None:
        """None — можно обрабатывать. Иначе причина отказа: "cooldown" или "chat_limit"."""
        now = self._now()

        last = self._last_by_user.get(user_id)
        if last is not None and now - last < self._cooldown:
            return "cooldown"

        hits = self._chat_hits[chat_id]
        hour_ago = now - 3600
        while hits and hits[0] < hour_ago:
            hits.popleft()
        if len(hits) >= self._hourly:
            return "chat_limit"

        # Отметку ставим только когда вопрос действительно принят: отказ не должен
        # продлевать паузу, иначе спам-кликер держал бы пользователя в блоке.
        self._last_by_user[user_id] = now
        hits.append(now)
        return None


def is_chat_allowed(chat_id: int) -> bool:
    """Пустой ALLOWED_CHAT_IDS = разрешены все чаты (поведение по умолчанию)."""
    return not config.ALLOWED_CHAT_IDS or chat_id in config.ALLOWED_CHAT_IDS
