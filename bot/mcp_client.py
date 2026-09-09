"""Клиент к серверному MCP Базы Знаний (https://knowledgebase.dodois.io/mcp).

Read-only соединение: без заголовка Mcp-Mode сервер не отдаёт write-инструменты
в tools/list вообще (проверено вживую curl'ом при выборе архитектуры) — значит
сама возможность записи физически недоступна из этого клиента, а не просто
не используется по договорённости.

Соединение живёт ровно один ответ партнёра (Session): открытие стоит трёх
HTTP-запросов, а перед Базой Знаний стоит защита по частоте запросов с одного IP
— она и ловила прежнюю схему «новое соединение на каждый вызов». Между разными
сообщениями Telegram общего состояния по-прежнему нет: у каждого ответа своя
сессия.
"""
import asyncio
import json
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx
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

    async with session() as kb:
        result = await kb.list_tools()

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


# Поля ответов KB, которые модели не нужны ни для выбора статьи, ни для ответа,
# но платятся как входные токены каждый раунд. Замер на search_content(limit=10):
# themes — 2373 символа из 8086, то есть 29% ответа уходило на UUID'ы тем.
_NOISE_FIELDS = frozenset({
    "themes", "authors", "status", "updatedAt", "createdAt", "publishedAt",
    "isWatermarksEnabled", "isCommentsEnabled", "isDarkMode", "fidelity",
    "rights", "translationType", "translations",
})


def _prune(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _prune(v) for k, v in obj.items() if k not in _NOISE_FIELDS}
    if isinstance(obj, list):
        return [_prune(v) for v in obj]
    return obj


def _compact_json(text: str) -> str:
    """Ответы KB — JSON с кириллицей, сериализованный через \\uXXXX-эскейпы:
    один русский символ занимает 6 байт вместо 1. Проверено вживую: при limit=50
    у search_content это раздувает ответ до ~95 КБ, наш _truncate (см. llm.py)
    обрубает его вслепую на первых нескольких результатах — самая релевантная
    статья может быть за пределами обрубленной части, и модель отвечает по
    оставшимся, менее подходящим. Перекодируем в обычный UTF-8, чтобы в тот же
    лимит символов помещалось в разы больше настоящего контента, и попутно
    выбрасываем служебные поля (_NOISE_FIELDS) — они только жгут токены."""
    try:
        return json.dumps(_prune(json.loads(text)), ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return text


# Перед Базой Знаний стоит антибот-защита: она режет по частоте запросов с одного
# IP и отдаёт HTML-страницу 403 вместо ответа MCP. Замеры 09.09.2026 с сервера:
# без пауз отказ приходит на 11–27-м запросе подряд, с паузой 0.5 с не приходит
# вовсе, а снятая блокировка держится ещё 10–25 секунд тишины — причём запросы
# под блокировкой её, судя по замерам, продлевают. Отсюда три числа ниже и одно
# соединение на весь ответ (см. Session): паузы между повторами должны перекрывать
# те самые 10–25 секунд, а не быть «на всякий случай короткими».
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5.0  # паузы 5 и 10 с; больше — партнёр устанет ждать ответа
# 403 в этом списке — та самая защита, а не отказ в правах: у KB отозванный или
# неверный токен даёт 401. Цена ошибки несимметрична: лишний повтор стоит двух
# запросов, а неповторённый отказ партнёр видит как «статьи прочитать не смог».
_TRANSIENT_STATUSES = frozenset({403, 408, 425, 429, 500, 502, 503, 504})


def _is_transient(exc: BaseException) -> bool:
    """Сбой соединения приходит завёрнутым в ExceptionGroup от anyio.TaskGroup,
    внутри которой лежит настоящая причина, — поэтому группу разворачиваем."""
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_transient(inner) for inner in exc.exceptions)
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_STATUSES
    return isinstance(exc, httpx.TransportError)


def _result_to_text(name: str, result: Any) -> str:
    parts = [getattr(block, "text", "") for block in result.content]
    text = "\n".join(p for p in parts if p) or "(пустой ответ от Базы Знаний)"
    if result.isError:
        return f"Ошибка инструмента {name}: {text}"
    return _compact_json(text)


class Session:
    """Соединение с Базой Знаний на время одного ответа партнёра.

    Раньше каждый вызов инструмента открывал своё соединение, а это три HTTP-запроса
    (initialize + notification + сам вызов) вместо одного: три статьи подряд давали
    двенадцать запросов за секунду и упирались в защиту по частоте. Здесь initialize
    платится один раз на ответ, а соединение переоткрывается только если оборвалось.
    """

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._client: ClientSession | None = None

    async def _open(self) -> tuple[Any, ClientSession]:
        stack = AsyncExitStack()
        try:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(config.KB_MCP_URL, headers=_headers())
            )
            client = await stack.enter_async_context(ClientSession(read, write))
            await client.initialize()
        except BaseException as exc:
            raise await self._close(stack, exc)
        return stack, client

    async def _connect(self) -> ClientSession:
        if self._client is None:
            self._stack, self._client = await self._open()
        return self._client

    @staticmethod
    async def _close(stack: Any, failure: BaseException | None = None) -> BaseException | None:
        """Закрывает соединение и возвращает настоящую причину сбоя.

        Соединение MCP живёт в своей task group: когда сервер отвечает отказом,
        группа отменяет ожидающий вызов, и наружу выходит голая CancelledError —
        причина (403 от защиты, обрыв сети) всплывает только при закрытии.
        Проверено смоуком на сервере: без этого разбора повтор не срабатывал
        именно в том сценарии, ради которого он написан.
        """
        cause = None
        if stack is not None:
            try:
                await stack.aclose()
            except BaseException as exc:
                cause = exc
        if failure is None:
            return cause
        if cause is not None and isinstance(failure, asyncio.CancelledError):
            return cause
        return failure

    async def _drop(self, failure: BaseException | None = None) -> BaseException | None:
        stack, self._stack, self._client = self._stack, None, None
        return await self._close(stack, failure)

    async def _retrying(self, what: str, operation):
        """Выполняет операцию в сессии, переживая временные отказы Базы Знаний."""
        for attempt in range(RETRY_ATTEMPTS):
            try:
                return await operation(await self._connect())
            except BaseException as exc:
                # Соединение после любого сбоя непригодно: сессия MCP живёт поверх
                # потока, продолжать в ней нельзя — закрываем и заодно достаём
                # настоящую причину (см. _close).
                failure = await self._drop(exc)
                # Настоящая отмена задачи (снятие хендлера, таймаут) транзиентной
                # не считается и повтору не подлежит — _is_transient её отсеет.
                if attempt == RETRY_ATTEMPTS - 1 or not _is_transient(failure):
                    raise failure
                delay = RETRY_DELAY_SECONDS * (attempt + 1)
                log.warning(
                    "KB MCP: временный сбой на %s (%s), повтор через %.1f с",
                    what, type(failure).__name__, delay,
                )
                await asyncio.sleep(delay)
        raise AssertionError("недостижимо: цикл повторов всегда завершается return или raise")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Вызывает инструмент KB, возвращает текст для LLM (без сырого JSON)."""
        if name in _wrapped_tool_names:
            arguments = {"request": arguments}
        result = await self._retrying(name, lambda client: client.call_tool(name, arguments))
        return _result_to_text(name, result)

    async def list_tools(self):
        return await self._retrying("tools/list", lambda client: client.list_tools())

    async def aclose(self) -> None:
        await self._drop()


@asynccontextmanager
async def session():
    """Соединение на время одного ответа партнёра."""
    kb = Session()
    try:
        yield kb
    finally:
        await kb.aclose()


async def call_tool(name: str, arguments: dict[str, Any]) -> str:
    """Разовый вызов вне общей сессии (список инструментов, проверки, скрипты)."""
    async with session() as kb:
        return await kb.call_tool(name, arguments)
