"""Цикл LLM-с-инструментами: вопрос партнёра -> (0..N вызовов инструментов KB) -> ответ.

Форма цикла — по образцу handleAsk из проекта Swarm Brain
(supabase/functions/swarm-bot/handlers/knowledge.ts), адаптирована под read-only
инструменты MCP Базы Знаний вместо собственной Supabase-базы.
"""
import json
import logging

from openai import AsyncOpenAI

import config
import mcp_client
from partners import Partner

log = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

MAX_ROUNDS = 6
MAX_TOOL_RESULT_CHARS = 6000  # защита от раздувания контекста одним гигантским ответом KB

SYSTEM_PROMPT = (
    "Ты — помощник партнёров Dodo Pizza по внутренней Базе Знаний. "
    "Отвечай на вопрос, используя ТОЛЬКО инструменты Базы Знаний — никогда не отвечай по памяти "
    "и не выдумывай факты.\n\n"
    "Партнёр: {name}, страна: {country}.\n\n"
    "СТРАТЕГИЯ:\n"
    "1. Если вопрос без явного упоминания страны/рынка — сначала пробуй искать в контексте страны "
    "партнёра, но НЕ подставляй молча материалы другой страны, если не нашлось. Если найденное "
    "явно не по стране партнёра (например нашлось только по России, а партнёр из Сербии) — "
    "не выдавай это как ответ, а спроси уточнение: по какой стране/рынку партнёр имеет в виду.\n"
    "2. Если инструмент вернул пусто или ошибку — не сдавайся сразу: попробуй search_content с другой "
    "формулировкой запроса. Если снова пусто — честно скажи, что в Базе Знаний по этому вопросу ничего "
    "не нашлось, и предложи переформулировать.\n"
    "3. Используй get_spaces, если нужно понять, какие пространства вообще есть, прежде чем сузить поиск.\n\n"
    "Отвечай человеческим языком, на языке вопроса партнёра, без сырого JSON и служебных полей."
)


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + "\n...(обрезано)"


async def answer_question(question: str, partner: Partner) -> str:
    tools = await mcp_client.list_tools()

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(name=partner.name, country=partner.country)},
        {"role": "user", "content": question},
    ]

    for round_no in range(MAX_ROUNDS):
        response = await _client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="required" if round_no == 0 else "auto",
            max_tokens=1500,
        )
        message = response.choices[0].message
        tool_calls = message.tool_calls

        if not tool_calls:
            return message.content or "Не нашёл ответа в Базе Знаний."

        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [tc.model_dump() for tc in tool_calls],
        })

        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
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

    return "Не удалось получить ответ за отведённое число шагов — попробуй переформулировать вопрос."
