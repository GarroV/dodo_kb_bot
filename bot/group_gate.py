"""Гейт группового чата: в группе/супергруппе бот отвечает на обычный вопрос
партнёра (не команду) ТОЛЬКО по явному обращению — @упоминание в тексте или
reply на собственное сообщение бота. Личка не гейтится вообще — там и так
пишешь только боту, вопрос всегда явный.

Порт логики из Swarm Brain (supabase/functions/swarm-bot/lib/group-gate.ts).
Триггер «reply на сообщение бота» в оригинале отсутствовал — добавлен под
конкретное требование этого бота.
"""
import re
from dataclasses import dataclass


@dataclass
class GateVerdict:
    process: bool
    text: str = ""


def _mention_re(bot_username: str) -> re.Pattern:
    return re.compile(rf"@{re.escape(bot_username)}\b", re.IGNORECASE)


def _strip_mention(text: str, bot_username: str | None) -> str:
    if not bot_username:
        return text
    cleaned = _mention_re(bot_username).sub(" ", text)
    return re.sub(r"[ \t]+", " ", cleaned).strip()


def gate_group_text(raw_text: str | None, bot_username: str | None, is_reply_to_bot: bool) -> GateVerdict:
    text = (raw_text or "").strip()
    if not text:
        return GateVerdict(process=False)

    if is_reply_to_bot:
        return GateVerdict(process=True, text=_strip_mention(text, bot_username))

    if bot_username and _mention_re(bot_username).search(text):
        return GateVerdict(process=True, text=_strip_mention(text, bot_username))

    return GateVerdict(process=False)
