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

# Модель иногда выдумывает ссылки-заглушки (напр. your-link-here.com) — Telegram
# разворачивал их в превью произвольного стороннего сайта. Поэтому ссылки в
# ответе проверяются, а не берутся на доверие. Пропускаем два вида:
#   1) ссылки на саму Базу Знаний (их модель собирает из spaceId/articleId);
#   2) любые URL, которые ДОСЛОВНО встречались в ответах инструментов — это
#      ссылки из текста статей (стартовые страницы ТВ-бордов, гуглдоки,
#      документация плагинов), они полезны и выдумать их модель не могла.
_ALLOWED_LINK_PREFIX = "https://knowledgebase.dodois.io/"
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BARE_URL_RE = re.compile(r"https?://[^\s)]+")
_URL_TAIL_TRIM = ".,;:!?)»\"'"


def _is_allowed_link(url: str, tool_output: str) -> bool:
    if url.startswith(_ALLOWED_LINK_PREFIX):
        return True
    return url.rstrip(_URL_TAIL_TRIM) in tool_output


def _sanitize_links(text: str, tool_output: str = "") -> str:
    def _md_sub(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        return m.group(0) if _is_allowed_link(url, tool_output) else label

    text = _MD_LINK_RE.sub(_md_sub, text)

    def _bare_sub(m: re.Match) -> str:
        url = m.group(0)
        return url if _is_allowed_link(url, tool_output) else ""

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

MAX_ROUNDS = 8
MAX_TOOL_RESULT_CHARS = 8000  # защита от раздувания контекста одним гигантским ответом KB
# Полный текст статьи (get_content) нужен целиком — по excerpt'ам из поиска
# модель начинает домысливать шаги, которых в статье нет.
MAX_ARTICLE_CHARS = 14000
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
    "2. ОБЯЗАТЕЛЬНО читай статьи перед ответом. Результат search_content — это только заголовки и "
    "короткие обрывки текста (excerpt), их достаточно чтобы ВЫБРАТЬ статьи, но категорически "
    "недостаточно чтобы отвечать по существу. Выбрав 1–3 самые подходящие статьи, вызови для каждой "
    "get_content по её articleId и отвечай ТОЛЬКО по полученному полному тексту. Отвечать по одним "
    "excerpt'ам запрещено.\n"
    "3. Если инструмент вернул пусто или ошибку — не сдавайся сразу: попробуй search_content с другой "
    "формулировкой запроса. Если снова пусто — честно скажи, что в Базе Знаний по этому вопросу ничего "
    "не нашлось, и предложи переформулировать.\n"
    "4. Используй get_spaces, если нужно понять, какие пространства вообще есть, прежде чем сузить поиск.\n\n"
    "СТРАНА В ВОПРОСЕ — ЖЁСТКОЕ ПРАВИЛО:\n"
    "- Если партнёр назвал страну (например «для Сербии»), бери материалы ТОЛЬКО по этой стране. "
    "Материалы по другой стране (Казахстан, Россия и т.п.) НЕ являются ответом на вопрос про Сербию — "
    "не подставляй их молча вместо запрошенной страны.\n"
    "- Если по названной стране в Базе Знаний ничего нет — прямо скажи это («по Сербии материалов не "
    "нашлось»). Только после этого можешь предложить общие или другой страны материалы, явно "
    "пометив, к какой стране они относятся и что это не про запрошенную.\n"
    "- Если страна в вопросе не названа — используй все релевантные материалы, указывая у каждого "
    "пункта, к какой стране/рынку он относится.\n\n"
    "ФОРМАТ ОТВЕТА:\n"
    "- Отвечай на заданный вопрос по фактам из прочитанных статей: конкретные шаги, значения, "
    "названия пунктов меню — так, как написано в статье.\n"
    "- НИКАКИХ советов и рекомендаций от себя. Не добавляй пункты вроде «регулярно проверяйте», "
    "«убедитесь, что всё настроено правильно», «изучите логику» — если этого нет в тексте статьи, "
    "этого не должно быть в ответе. Общие рассуждения вместо содержания статьи — худшая ошибка.\n"
    "- Если партнёр просит именно список статей — дай список статей, а не пересказ шагов.\n"
    "- В конце отдельным блоком, ровно строкой «Источники:», перечисли по одной ссылке на строку на "
    "реально прочитанные статьи: https://knowledgebase.dodois.io/next/article/{spaceId}/{articleId}, "
    "подставив настоящие spaceId и articleId из результата search_content. Не давай ссылок на "
    "статьи, которые не читал через get_content. НИКОГДА не придумывай другой домен или адрес.\n"
    "- Пиши по делу. Не добавляй пустых фраз вроде «дайте знать, если нужно больше информации» и не "
    "обещай сделать то, что должно быть уже сделано в этом же ответе.\n\n"
    "Отвечай человеческим языком, на языке вопроса партнёра, без сырого JSON и служебных полей."
)


def _model_extra_kwargs(model: str) -> dict:
    """Модели gpt-5* в /v1/chat/completions не принимают function tools вместе с
    рассуждениями: нужен явный reasoning_effort='none' (иначе 400). Для
    gpt-4o-семейства параметра быть не должно вообще."""
    if model.startswith("gpt-5"):
        return {"reasoning_effort": "none"}
    return {}


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...(обрезано)"


async def answer_question(question: str) -> Answer:
    tools = await mcp_client.list_tools()

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    # Всё, что вернули инструменты за диалог — по нему _sanitize_links отличает
    # ссылку из статьи от выдуманной моделью.
    tool_outputs: list[str] = []

    prompt_tokens = completion_tokens = total_tokens = 0
    rounds_used = 0

    for round_no in range(MAX_ROUNDS):
        rounds_used = round_no + 1
        response = await _client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="required" if round_no == 0 else "auto",
            # max_completion_tokens, а не max_tokens: модели gpt-5* последний
            # параметр не принимают вообще (400 unsupported_parameter), а
            # gpt-4o-семейство понимает оба — так конфиг модели остаётся
            # свободно переключаемым через OPENAI_MODEL.
            max_completion_tokens=1500,
            **_model_extra_kwargs(config.OPENAI_MODEL),
        )
        if response.usage:
            prompt_tokens += response.usage.prompt_tokens
            completion_tokens += response.usage.completion_tokens
            total_tokens += response.usage.total_tokens

        message = response.choices[0].message
        tool_calls = message.tool_calls

        if not tool_calls:
            return Answer(
                text=_sanitize_links(message.content or "Не нашёл ответа в Базе Знаний.", "\n".join(tool_outputs)),
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
            limit = MAX_ARTICLE_CHARS if tc.function.name == "get_content" else MAX_TOOL_RESULT_CHARS
            truncated = _truncate(result, limit)
            tool_outputs.append(truncated)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": truncated})

    return Answer(
        text="Не удалось получить ответ за отведённое число шагов — попробуй переформулировать вопрос.",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        rounds=rounds_used,
    )
