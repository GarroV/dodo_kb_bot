"""Клиент к серверному MCP Базы Знаний (https://knowledgebase.dodois.io/mcp).

Read-only соединение: без заголовка Mcp-Mode сервер не отдаёт write-инструменты
в tools/list вообще (проверено вживую curl'ом при выборе архитектуры) — значит
сама возможность записи физически недоступна из этого клиента, а не просто
не используется по договорённости.

Каждый вызов открывает новое соединение (initialize → запрос → закрыть). Для
объёма партнёрских вопросов это не узкое место, а простой и надёжный вариант —
никакого общего состояния между конкурентными сообщениями Telegram.
"""
import logging
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

import config

log = logging.getLogger(__name__)

_tools_cache: list[dict[str, Any]] | None = None


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.KB_MCP_TOKEN}"}


async def list_tools(force_refresh: bool = False) -> list[dict[str, Any]]:
    """Инструменты KB в формате OpenAI function-tools (кэшируются в процессе)."""
    global _tools_cache
    if _tools_cache is not None and not force_refresh:
        return _tools_cache

    async with streamablehttp_client(config.KB_MCP_URL, headers=_headers()) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    tools = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema,
            },
        }
        for tool in result.tools
    ]
    log.info("KB MCP: доступно инструментов — %d (%s)", len(tools), ", ".join(t["function"]["name"] for t in tools))
    _tools_cache = tools
    return tools


async def call_tool(name: str, arguments: dict[str, Any]) -> str:
    """Вызывает инструмент KB, возвращает текст для LLM (без сырого JSON)."""
    async with streamablehttp_client(config.KB_MCP_URL, headers=_headers()) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)

    parts = [getattr(block, "text", "") for block in result.content]
    text = "\n".join(p for p in parts if p) or "(пустой ответ от Базы Знаний)"
    if result.isError:
        return f"Ошибка инструмента {name}: {text}"
    return text
