"""Telegram-бот-прослойка к Базе Знаний Dodo Pizza для партнёров (long polling, aiogram 3).

Партнёры не получают ни личный логин, ни MCP-токен от Базы Знаний — единственная
точка входа это этот бот с одним сервисным PAT (см. config.KB_MCP_TOKEN,
mcp_client.py). Кто вообще может писать боту — список в partners.py.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.utils.chat_action import ChatActionSender

import config
import llm
import partners

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

dp = Dispatcher()

TELEGRAM_MESSAGE_LIMIT = 4096
NO_ACCESS_TEXT = "Доступ закрыт. Обратись к администратору, чтобы тебя добавили в список партнёров."


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


@dp.message()
async def handle_question(message: types.Message) -> None:
    text = (message.text or "").strip()
    if not text:
        return

    partner = partners.get_partner(message.from_user.id)
    if not partner:
        await message.answer(NO_ACCESS_TEXT)
        return

    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            answer = await llm.answer_question(text, partner)
    except Exception:
        log.exception("Ошибка обработки вопроса от партнёра %s (%s)", partner.telegram_id, partner.name)
        answer = "Произошла ошибка при обращении к Базе Знаний. Попробуй ещё раз чуть позже."

    for chunk in _split_message(answer):
        await message.answer(chunk)


async def main() -> None:
    bot = Bot(config.BOT_TOKEN)
    log.info("Стартуем long polling…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
