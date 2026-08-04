"""Telegram-бот-прослойка к Базе Знаний Dodo Pizza для партнёров (long polling, aiogram 3).

Партнёры не получают ни личный логин, ни MCP-токен от Базы Знаний — единственная
точка входа это этот бот с одним сервисным PAT (см. config.KB_MCP_TOKEN,
mcp_client.py). Кто вообще может писать боту — список в partners.py.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.utils.chat_action import ChatActionSender

import config
import group_gate
import llm
import partners
import usage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

dp = Dispatcher()

TELEGRAM_MESSAGE_LIMIT = 4096
NO_ACCESS_TEXT = "Доступ закрыт. Обратись к администратору, чтобы тебя добавили в список партнёров."

# Заполняются на старте (см. _on_startup) — нужны гейту группового чата, чтобы
# узнавать @упоминание себя и reply на своё же сообщение.
_bot_username: str | None = None
_bot_id: int | None = None


async def _on_startup(bot: Bot) -> None:
    global _bot_username, _bot_id
    me = await bot.get_me()
    _bot_username = me.username
    _bot_id = me.id
    log.info("Бот запущен как @%s (id=%d)", _bot_username, _bot_id)


dp.startup.register(_on_startup)


def _split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        parts.append(text[:limit])
        text = text[limit:]
    return parts


@dp.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    partner = partners.get_partner(message.from_user.id)
    if not partner:
        await message.answer(NO_ACCESS_TEXT)
        return
    await message.answer(f"Привет, {partner.name}! Пиши вопрос по Базе Знаний — найду ответ.")


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message) -> None:
    # Молчим и для чужих, и для случая, когда ADMIN_TELEGRAM_ID вообще не задан —
    # не подтверждаем и не опровергаем существование команды посторонним.
    if config.ADMIN_TELEGRAM_ID is None or message.from_user.id != config.ADMIN_TELEGRAM_ID:
        return

    stats = usage.summarize()
    lines = [
        f"Транзакций: {stats['transactions']} (ошибок: {stats['failed']})",
        f"Токенов всего: {stats['total_tokens']}",
    ]
    if stats["by_partner"]:
        lines.append("")
        lines.append("По партнёрам:")
        by_tokens = sorted(stats["by_partner"].items(), key=lambda kv: -kv[1]["total_tokens"])
        for name, s in by_tokens:
            lines.append(f"  {name}: {s['transactions']} тр., {s['total_tokens']} ток.")
    await message.answer("\n".join(lines))


@dp.message()
async def handle_question(message: types.Message) -> None:
    raw_text = (message.text or "").strip()
    if not raw_text:
        return

    if message.chat.type == "private":
        text = raw_text
    else:
        # Групповой чат: обычный вопрос (не команда — те уже разобраны выше)
        # обрабатываем только по явному обращению — @тег или reply на бота.
        is_reply_to_bot = bool(
            message.reply_to_message
            and message.reply_to_message.from_user
            and message.reply_to_message.from_user.id == _bot_id
        )
        verdict = group_gate.gate_group_text(raw_text, _bot_username, is_reply_to_bot)
        if not verdict.process:
            return
        text = verdict.text

    if not text:
        return

    partner = partners.get_partner(message.from_user.id)
    if not partner:
        await message.answer(NO_ACCESS_TEXT)
        return

    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            result = await llm.answer_question(text, partner)
        usage.record(
            telegram_id=partner.telegram_id,
            partner_name=partner.name,
            country=partner.country,
            model=config.OPENAI_MODEL,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            rounds=result.rounds,
            ok=True,
        )
        answer_text = result.text
    except Exception:
        log.exception("Ошибка обработки вопроса от партнёра %s (%s)", partner.telegram_id, partner.name)
        usage.record(
            telegram_id=partner.telegram_id,
            partner_name=partner.name,
            country=partner.country,
            model=config.OPENAI_MODEL,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            rounds=0,
            ok=False,
        )
        answer_text = "Произошла ошибка при обращении к Базе Знаний. Попробуй ещё раз чуть позже."

    for chunk in _split_message(answer_text):
        await message.answer(chunk)


async def main() -> None:
    bot = Bot(config.BOT_TOKEN)
    log.info("Стартуем long polling…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
