"""Цикл LLM-с-инструментами: вопрос партнёра -> (0..N вызовов инструментов KB) -> ответ.

Форма цикла — по образцу handleAsk из проекта Swarm Brain
(supabase/functions/swarm-bot/handlers/knowledge.ts), адаптирована под read-only
инструменты MCP Базы Знаний вместо собственной Supabase-базы.
"""
import json
import logging
import re
from dataclasses import dataclass

from openai import AsyncOpenAI

import config
import mcp_client

log = logging.getLogger(__name__)

# Единственный домен, с которого разрешено давать ссылки в ответе — реальная
# База Знаний. Модель иногда выдумывает ссылки-заглушки (напр. your-link-here.com),
# а у Telegram они разворачиваются в превью произвольного стороннего сайта —
# поэтому это не рекомендация модели, а жёсткая пост-обработка её ответа.
_ALLOWED_LINK_PREFIX = "https://knowledgebase.dodois.io/"
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BARE_URL_RE = re.compile(r"https?://[^\s)]+")


def _sanitize_links(text: str) -> str:
    def _md_sub(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        return m.group(0) if url.startswith(_ALLOWED_LINK_PREFIX) else label

    text = _MD_LINK_RE.sub(_md_sub, text)

    def _bare_sub(m: re.Match) -> str:
        url = m.group(0)
        return url if url.startswith(_ALLOWED_LINK_PREFIX) else ""

    text = _BARE_URL_RE.sub(_bare_sub, text)
    return re.sub(r"[ \t]{2,}", " ", text)


@dataclass
class Answer:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    rounds: int = 0

_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

MAX_ROUNDS = 6
MAX_TOOL_RESULT_CHARS = 8000  # защита от раздувания контекста одним гигантским ответом KB
# search_content по умолчанию отдаёт до 50 результатов — это легко за пределами
# MAX_TOOL_RESULT_CHARS, и _truncate обрубает вслепую, теряя самые релевантные
# (backend ранжирует хорошо, но обрезка после него портит результат). Не
# полагаемся на то, что модель сама укажет разумный limit — жёстко ограничиваем.
SEARCH_CONTENT_MAX_LIMIT = 10

SYSTEM_PROMPT = (
    "Ты — помощник партнёров Dodo Pizza по внутренней Базе Знаний. "
    "Отвечай на вопрос, используя ТОЛЬКО инструменты Базы Знаний — никогда не отвечай по памяти "
    "и не выдумывай факты.\n\n"
    "СТРАТЕГИЯ ПОИСКА:\n"
    "1. search_content — это поиск по ключевым словам, а не по смыслу: он куда чувствительнее к "
    "точным словам, чем кажется. В пределах ОДНОГО вызова доверяй порядку выдачи (верхние результаты "
    "самые релевантные). Но База Знаний двуязычная — часть материалов только на русском, часть "
    "только на английском (особенно международные темы: эквайринг, интеграции, запуск в новой "
    "стране). Если вопрос может касаться нескольких стран или первый поиск на русском выглядит "
    "неполным — ОБЯЗАТЕЛЬНО сделай ещё один search_content с другой формулировкой, включая короткие "
    "английские термины по теме (например 'acquiring', 'PayU', 'plugin', 'setup'), а не только "
    "пересказ вопроса по-русски. Не останавливайся после одного вызова, если тема похожа на "
    "международную.\n"
    "2. Страна/рынок партнёра боту заранее не известны. Если верхние результаты относятся к разным "
    "странам — не отбрасывай их и не пытайся угадать одну: используй все релевантные, явно указывая, "
    "к какой стране/рынку относится каждый пункт.\n"
    "3. Если инструмент вернул пусто или ошибку — не сдавайся сразу: попробуй search_content с другой "
    "формулировкой запроса. Если снова пусто — честно скажи, что в Базе Знаний по этому вопросу ничего "
    "не нашлось, и предложи переформулировать.\n"
    "4. Используй get_spaces, если нужно понять, какие пространства вообще есть, прежде чем сузить поиск.\n\n"
    "ФОРМАТ ОТВЕТА:\n"
    "- Не пересказывай найденное построчно «статья — ссылка». Синтезируй содержимое статей в связный "
    "ответ по существу вопроса, при необходимости — с подзаголовками по темам.\n"
    "- В конце отдельным блоком «Источники:» перечисли по одной ссылке на строку на реально "
    "использованные статьи: https://knowledgebase.dodois.io/next/article/{spaceId}/{articleId}, "
    "подставив настоящие spaceId и articleId из результата search_content (они есть в каждом найденном "
    "результате — отдельный инструмент за ними вызывать не нужно). НИКОГДА не придумывай другой домен "
    "или адрес — если spaceId/articleId неизвестны, просто не добавляй ссылку на эту статью.\n"
    "- Пиши по делу. Не добавляй пустых фраз вроде «дайте знать, если нужно больше информации» и не "
    "обещай сделать то, что должно быть уже сделано в этом же ответе.\n\n"
    "Отвечай человеческим языком, на языке вопроса партнёра, без сырого JSON и служебных полей."
)


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + "\n...(обрезано)"


async def answer_question(question: str) -> Answer:
    tools = await mcp_client.list_tools()

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    prompt_tokens = completion_tokens = total_tokens = 0
    rounds_used = 0

    for round_no in range(MAX_ROUNDS):
        rounds_used = round_no + 1
        response = await _client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="required" if round_no == 0 else "auto",
            max_tokens=1500,
        )
        if response.usage:
            prompt_tokens += response.usage.prompt_tokens
            completion_tokens += response.usage.completion_tokens
            total_tokens += response.usage.total_tokens

        message = response.choices[0].message
        tool_calls = message.tool_calls

        if not tool_calls:
            return Answer(
                text=_sanitize_links(message.content or "Не нашёл ответа в Базе Знаний."),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                rounds=rounds_used,
            )

        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [tc.model_dump() for tc in tool_calls],
        })

        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
                if tc.function.name == "search_content":
                    args["limit"] = min(args.get("limit") or SEARCH_CONTENT_MAX_LIMIT, SEARCH_CONTENT_MAX_LIMIT)
                result = await mcp_client.call_tool(tc.function.name, args)
            except Exception:
                # Полная трассировка — только в серверный лог. В модель (и потенциально
                # в ответ партнёру) уходит нейтральный текст: сырое исключение может
                # содержать внутренние детали (URL, структура запроса и т.п.).
                log.exception("Ошибка вызова инструмента %s", tc.function.name)
                result = "Инструмент временно недоступен. Попробуй переформулировать запрос."
            # Контент KB не пишем в лог целиком — это чужие корпоративные данные под
            # доступом по allowlist'у, а докер-логи читает более широкий круг людей.
            log.info("[tool] %s args_len=%d result_len=%d", tc.function.name, len(tc.function.arguments or ""), len(result))
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": _truncate(result)})

    return Answer(
        text="Не удалось получить ответ за отведённое число шагов — попробуй переформулировать вопрос.",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        rounds=rounds_used,
    )
