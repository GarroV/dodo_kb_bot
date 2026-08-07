"""Telegram-бот-прослойка к Базе Знаний Dodo Pizza (long polling, aiogram 3).

Партнёры не получают ни личный логин, ни MCP-токен от Базы Знаний — единственная
точка входа это бот с одним сервисным read-only PAT (см. config.KB_MCP_TOKEN,
mcp_client.py).

Границы доступа:
  * личка закрыта для вопросов — бот работает в групповых чатах;
  * в группе реагирует только на явное обращение: /kb_ask, reply на своё
    сообщение или @упоминание (последнее доходит лишь при выключенном Group
    Privacy Mode) — остальную переписку не обрабатывает, см. group_gate.py;
  * ALLOWED_CHAT_IDS, если задан, ограничивает список чатов (limits.py);
  * частота ограничена: каждый вопрос — это вызовы LLM, то есть деньги.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.utils.chat_action import ChatActionSender

import config
import group_gate
import limits
import llm
import usage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

dp = Dispatcher()

TELEGRAM_MESSAGE_LIMIT = 4096

# Партнёры международные, поэтому свои строки бот тоже подаёт на двух языках.
# Определение языка — одно на весь проект, в llm.lang_of (кириллица -> русский,
# для сообщений без текста — по language_code профиля Telegram).
TEXTS = {
    "private_closed": {
        "ru": "Вопросы по Базе Знаний я принимаю только в групповом чате — добавь меня "
              "в чат с командой и обратись через @упоминание, reply или команду /kb_ask.",
        "en": "I only take Knowledge Base questions in a group chat — add me to your team's "
              "chat and reach me with an @mention, a reply, or the /kb_ask command.",
    },
    "greeting": {
        "ru": "Привет! Обращайся ко мне через @упоминание, reply или командой "
              "/kb_ask <вопрос> — найду ответ в Базе Знаний.",
        "en": "Hi! Reach me with an @mention, a reply, or /kb_ask <question> — "
              "I'll find the answer in the Knowledge Base.",
    },
    "searching": {
        "ru": "Ищу в Базе Знаний…",
        "en": "Searching the Knowledge Base…",
    },
    "kb_ask_empty": {
        "ru": "Напиши вопрос после команды: /kb_ask как настроить кассу в Додо ИС",
        "en": "Add your question after the command: /kb_ask how to set up a cash register in Dodo IS",
    },
    "info": {
        "ru": (
            "Бот Базы Знаний (@dodo_kb_bot) — отвечает на вопросы по Базе Знаний Dodo.\n\n"
            "Как спросить в этом чате:\n"
            "/kb_ask как настроить кассу ресторана\n\n"
            "Что придёт: короткий ответ по существу и ссылки на статьи, за 10–20 секунд. "
            "Отвечает на языке вопроса и только по Базе Знаний — если материала нет, скажет прямо.\n\n"
            "Советы: один конкретный вопрос за раз; называйте страну («в Сербии»); "
            "каждый вопрос формулируйте целиком — предыдущие сообщения бот не помнит.\n\n"
            "Бот не читает переписку в группе — он видит только обращения к нему: команду "
            "/kb_ask и ответы (реплаи) на его собственные сообщения. Упоминание через собаку "
            "он не получает вообще, поэтому на него не отвечает."
        ),
        "en": (
            "Knowledge Base bot (@dodo_kb_bot) — answers questions from the Dodo Knowledge Base.\n\n"
            "How to ask in this chat:\n"
            "/kb_ask how to configure the restaurant cash register\n\n"
            "What you get: a short answer plus links to the source articles, in 10–20 seconds. "
            "It replies in the language of your question and only from the Knowledge Base — "
            "if there is nothing on the topic, it says so.\n\n"
            "Tips: ask one specific question at a time; name the country (\"in Serbia\"); "
            "make each question self-contained — the bot doesn't remember previous messages.\n\n"
            "The bot does not read the group conversation — it only sees messages addressed to "
            "it: the /kb_ask command and replies to its own messages. An @mention never reaches "
            "it, which is why it stays silent on those."
        ),
    },
    "cooldown": {
        "ru": "Секунду — я ещё отвечаю на предыдущий вопрос. Повтори чуть позже.",
        "en": "One moment — I'm still working on the previous question. Please try again shortly.",
    },
    "chat_limit": {
        "ru": "В этом чате исчерпан лимит вопросов на час. Попробуй позже.",
        "en": "This chat has reached its hourly question limit. Please try again later.",
    },
    "error": {
        "ru": "Произошла ошибка при обращении к Базе Знаний. Попробуй ещё раз чуть позже.",
        "en": "Something went wrong while querying the Knowledge Base. Please try again a bit later.",
    },
}


def _t(key: str, lang: str) -> str:
    return TEXTS[key][lang]

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

    # Меню команд в интерфейсе Telegram: партнёр видит подсказку, набирая «/».
    # /stats не публикуем — она только для админа.
    await bot.set_my_commands([
        types.BotCommand(command="kb_ask", description="Спросить Базу Знаний / Ask the Knowledge Base"),
        types.BotCommand(command="kb_info", description="Как пользоваться ботом / How to use the bot"),
    ])


dp.startup.register(_on_startup)


def _split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Режет длинный ответ по границам строк. Резать вслепую по лимиту нельзя:
    разрыв приходится в том числе на середину ссылки, и она перестаёт быть
    кликабельной, а половина адреса выглядит как мусор."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ""
        # Строка сама длиннее лимита (например гигантский URL) — только тогда
        # режем посимвольно, иначе её вообще не отправить.
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        parts.append(current)
    return parts


@dp.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    lang = llm.lang_of(None, message.from_user.language_code)
    if message.chat.type == "private":
        await message.answer(_t("private_closed", lang))
        return
    await message.answer(_t("greeting", lang))


@dp.message(Command("kb_info"))
async def cmd_kb_info(message: types.Message) -> None:
    # Справка полезна и в личке, и в группе — в отличие от вопросов, её не гейтим.
    await message.answer(_t("info", llm.lang_of(None, message.from_user.language_code)))


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message) -> None:
    # Молчим и для чужих, и для случая, когда ADMIN_TELEGRAM_ID вообще не задан —
    # не подтверждаем и не опровергаем существование команды посторонним.
    if config.ADMIN_TELEGRAM_ID is None or message.from_user.id != config.ADMIN_TELEGRAM_ID:
        # Логируем отказ: иначе «/stats молчит» неотличимо от «команда не дошла».
        log.info(
            "[stats] отказ: from_id=%s admin_id=%s chat=%s",
            message.from_user.id, config.ADMIN_TELEGRAM_ID, message.chat.type,
        )
        return
    log.info("[stats] выдаю сводку для from_id=%s", message.from_user.id)

    stats = usage.summarize()
    lines = [
        f"Транзакций: {stats['transactions']} (ошибок: {stats['failed']})",
        f"Токенов всего: {stats['total_tokens']} (из кэша: {stats['cached_tokens']})",
        f"Стоимость: ${stats['cost_usd']:.4f}",
        f"Модель сейчас: {config.OPENAI_MODEL}",
    ]
    if stats["by_user"]:
        lines.append("")
        lines.append("По пользователям:")
        by_tokens = sorted(stats["by_user"].items(), key=lambda kv: -kv[1]["total_tokens"])
        for name, s in by_tokens:
            lines.append(
                f"  {name}: {s['transactions']} тр., {s['total_tokens']} ток., ${s['cost_usd']:.4f}"
            )
    await message.answer("\n".join(lines))


_throttle = limits.Throttle()


async def _answer_and_reply(message: types.Message, text: str) -> None:
    """Прогоняет text через LLM, пишет usage и отвечает в чат — общий хвост
    для гейта по @упоминанию/reply и для команды /kb_ask."""
    user_id = message.from_user.id
    user_name = message.from_user.first_name or message.from_user.username or str(user_id)
    lang = llm.lang_of(text, message.from_user.language_code)

    if not limits.is_chat_allowed(message.chat.id):
        # Молча: в неразрешённом чате бот не должен даже подтверждать, что жив.
        log.info("[access] чат не в списке разрешённых: chat_id=%s", message.chat.id)
        return

    # chat_id в логе — единственный способ узнать id чата, чтобы вписать его в
    # ALLOWED_CHAT_IDS: в интерфейсе Telegram он не показывается.
    log.info(
        "[ask] chat_id=%s chat=%s from_id=%s",
        message.chat.id, message.chat.title or message.chat.type, user_id,
    )

    denied = _throttle.check(user_id, message.chat.id)
    if denied:
        log.info("[limit] %s: from_id=%s chat_id=%s", denied, user_id, message.chat.id)
        await message.answer(_t(denied, lang))
        return

    # Поиск по Базе Знаний занимает несколько секунд (несколько раундов
    # tool-calling) — короткая отбивка, чтобы не выглядело, будто бот завис.
    await message.answer(_t("searching", lang))

    try:
        async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
            result = await llm.answer_question(text, lang)
        usage.record(
            telegram_id=user_id,
            user_name=user_name,
            model=config.OPENAI_MODEL,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            rounds=result.rounds,
            ok=True,
            cached_prompt_tokens=result.cached_prompt_tokens,
        )
        answer_text = result.text
    except Exception:
        log.exception("Ошибка обработки вопроса от %s (%s)", user_id, user_name)
        usage.record(
            telegram_id=user_id,
            user_name=user_name,
            model=config.OPENAI_MODEL,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            rounds=0,
            ok=False,
        )
        answer_text = _t("error", lang)

    # Превью ссылок отключено: даже если санитайзер в llm.py что-то пропустит,
    # разворачиваться в карточку постороннего сайта в чате партнёров нечему.
    preview_off = types.LinkPreviewOptions(is_disabled=True)
    for chunk in _split_message(answer_text):
        await message.answer(chunk, link_preview_options=preview_off)


@dp.message(Command("kb_ask"))
async def cmd_kb_ask(message: types.Message, command: CommandObject) -> None:
    # Команда доставляется боту всегда, даже при включённом Group Privacy Mode —
    # в отличие от обычного текста с @упоминанием (Telegram фильтрует его сам,
    # до нашего кода, если privacy не выключен явно через @BotFather).
    question = (command.args or "").strip()
    lang = llm.lang_of(question, message.from_user.language_code)

    if message.chat.type == "private":
        await message.answer(_t("private_closed", lang))
        return

    if not question:
        await message.answer(_t("kb_ask_empty", lang))
        return

    await _answer_and_reply(message, question)


@dp.message()
async def handle_question(message: types.Message) -> None:
    raw_text = (message.text or "").strip()
    if not raw_text:
        return

    if message.chat.type == "private":
        # Личка закрыта для вопросов — единственное, что там разрешено, это
        # команды (/start, /stats), они разобраны выше и сюда не попадают.
        await message.answer(_t("private_closed", llm.lang_of(raw_text, message.from_user.language_code)))
        return

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

    await _answer_and_reply(message, text)


async def main() -> None:
    bot = Bot(config.BOT_TOKEN)
    log.info("Стартуем long polling…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
