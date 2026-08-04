"""Клиент к серверному MCP Базы Знаний (https://knowledgebase.dodois.io/mcp).

Read-only соединение: без заголовка Mcp-Mode сервер не отдаёт write-инструменты
в tools/list вообще (проверено вживую curl'ом при выборе архитектуры) — значит
сама возможность записи физически недоступна из этого клиента, а не просто
не используется по договорённости.

Каждый вызов открывает новое соединение (initialize → запрос → закрыть). Для
объёма партнёрских вопросов это не узкое место, а простой и надёжный вариант —
никакого общего состояния между конкурентными сообщениями Telegram.
"""
import json
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

import config

log = logging.getLogger(__name__)

_tools_cache: list[dict[str, Any]] | None = None
# Имена инструментов, чья реальная схема заворачивает все параметры в один
# объект request (см. _unwrap_request_schema) — им при вызове нужно то же
# самое обёртывание аргументов обратно.
_wrapped_tool_names: set[str] = set()


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.KB_MCP_TOKEN}"}


def _unwrap_request_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Часть инструментов KB (автогенерация над REST-контроллерами) требует все
    параметры одним вложенным объектом: {"request": {"query": ..., ...}}.
    Проверено вживую: gpt-4o-mini регулярно не может собрать такой вложенный
    JSON в tool-calling — присылает аргументы плоско, вызов падает с ошибкой
    на сервере, а модель тихо решает, что в Базе Знаний ничего нет (хотя
    инструмент просто не сработал). Разворачиваем схему до плоской здесь, а
    в call_tool заворачиваем аргументы обратно — модели вложенность вообще
    не видна."""
    props = schema.get("properties", {})
    if set(schema.get("required", [])) == {"request"} and set(props.keys()) == {"request"}:
        inner = props["request"]
        if inner.get("type") == "object":
            return inner
    return schema


async def list_tools(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Инструменты KB в формате OpenAI function-tools (кэшируются в процессе)."""
    global _tools_cache
    if _tools_cache is not None and not force_refresh:
        return _tools_cache

    async with streamablehttp_client(config.KB_MCP_URL, headers=_headers()) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    _wrapped_tool_names.clear()
    tools = []
    for tool in result.tools:
        flat_schema = _unwrap_request_schema(tool.inputSchema)
        if flat_schema is not tool.inputSchema:
            _wrapped_tool_names.add(tool.name)
        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": flat_schema,
            },
        })
    log.info("KB MCP: доступно инструментов — %d (%s)", len(tools), ", ".join(t["function"]["name"] for t in tools))
    _tools_cache = tools
    return tools


def _compact_json(text: str) -> str:
    """Ответы KB — JSON с кириллицей, сериализованный через \\uXXXX-эскейпы:
    один русский символ занимает 6 байт вместо 1. Проверено вживую: при limit=50
    у search_content это раздувает ответ до ~95 КБ, наш _truncate (см. llm.py)
    обрубает его вслепую на первых нескольких результатах — самая релевантная
    статья может быть за пределами обрубленной части, и модель отвечает по
    оставшимся, менее подходящим. Перекодируем в обычный UTF-8, чтобы в тот же
    лимит символов помещалось в разы больше настоящего контента."""
    try:
        return json.dumps(json.loads(text), ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return text


async def call_tool(name: str, arguments: dict[str, Any]) -> str:
    """Вызывает инструмент KB, возвращает текст для LLM (без сырого JSON)."""
    if name in _wrapped_tool_names:
        arguments = {"request": arguments}

    async with streamablehttp_client(config.KB_MCP_URL, headers=_headers()) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)

    parts = [getattr(block, "text", "") for block in result.content]
    text = "\n".join(p for p in parts if p) or "(пустой ответ от Базы Знаний)"
    if result.isError:
        return f"Ошибка инструмента {name}: {text}"
    return _compact_json(text)
