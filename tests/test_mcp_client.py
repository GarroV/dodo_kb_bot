"""Адаптация ответов и схем MCP Базы Знаний.

Разворот обёртки `request` — причина того, что поиск когда-то вообще не работал:
модель присылала аргументы плоско, сервер отвечал ошибкой, а бот сообщал, что
ничего не нашлось.
"""
import json

import mcp_client

WRAPPED = {
    "type": "object",
    "properties": {
        "request": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
    },
    "required": ["request"],
}
FLAT = {"type": "object", "properties": {}}


def test_wrapped_schema_is_unwrapped_for_the_model():
    flat = mcp_client._unwrap_request_schema(WRAPPED)
    assert set(flat["properties"]) == {"query"}
    assert flat["required"] == ["query"]


def test_schema_without_wrapper_is_left_alone():
    assert mcp_client._unwrap_request_schema(FLAT) is FLAT


def test_noise_fields_are_pruned():
    raw = json.dumps({
        "results": [{
            "articleId": "a-1",
            "articleTitle": "Настройка касс",
            "excerpt": "текст",
            "spaceId": "s-1",
            "themes": [{"id": "t-1", "name": "Кассы"}],
            "authors": [{"name": "Кто-то"}],
            "status": "published",
            "isWatermarksEnabled": False,
        }]
    })
    out = json.loads(mcp_client._compact_json(raw))
    result = out["results"][0]
    assert set(result) == {"articleId", "articleTitle", "excerpt", "spaceId"}


def test_cyrillic_is_not_escaped_after_compaction():
    raw = json.dumps({"articleTitle": "Настройка касс"})  # ensure_ascii=True по умолчанию
    assert "\\u" in raw
    assert "Настройка касс" in mcp_client._compact_json(raw)


def test_non_json_payload_passes_through():
    assert mcp_client._compact_json("не JSON") == "не JSON"


# --- Устойчивость к антибот-защите перед Базой Знаний -------------------------
#
# Инцидент 09.09.2026: партнёр спросил про ТВ-борды по-английски, три вызова
# get_content подряд получили HTML-страницу 403 от защиты по частоте запросов,
# и бот сообщил, что не смог прочитать статьи. Замер: без пауз отказ приходит
# на 11-м запросе, блокировка снимается за ≤5 секунд — то есть повтор спасает.

import asyncio
import types

import httpx
import pytest


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://knowledgebase.dodois.io/mcp")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def _grouped(exc: Exception) -> BaseException:
    """MCP заворачивает сбой соединения в ExceptionGroup от anyio.TaskGroup —
    именно в таком виде ошибка приходит в call_tool, а не голым исключением."""
    return ExceptionGroup("unhandled errors in a TaskGroup", [exc])


class _FakeClient:
    """Подменяет ClientSession: отдаёт заранее заданный сценарий ответов.

    Сценарий общий для всех соединений подряд — Базе Знаний всё равно, первое
    это подключение или переоткрытие после сбоя, она просто отвечает по очереди.
    """

    def __init__(self, script: list) -> None:
        self._script = script
        self.calls: list[str] = []

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append(name)
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _ok_result(text: str = '{"ok": true}'):
    return types.SimpleNamespace(content=[types.SimpleNamespace(text=text)], isError=False)


def _session_over(script: list) -> tuple[mcp_client.Session, dict]:
    """Сессия, у которой соединение подменено фейком; opened считает,
    сколько раз пришлось открывать соединение заново."""
    session = mcp_client.Session()
    state = {"opened": 0, "client": None}
    remaining = list(script)

    async def fake_open(self):
        state["opened"] += 1
        state["client"] = _FakeClient(remaining)
        return None, state["client"]

    session._open = types.MethodType(fake_open, session)
    return session, state


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    """Пауза между попытками в тестах не нужна — проверяем логику, не таймеры."""
    monkeypatch.setattr(mcp_client, "RETRY_DELAY_SECONDS", 0)


def test_forbidden_from_the_bot_shield_is_retried():
    session, state = _session_over([_grouped(_http_error(403)), _ok_result()])
    result = asyncio.run(session.call_tool("get_content", {"articleId": "a-1"}))
    assert '"ok": true' in result
    assert state["opened"] == 2  # соединение после отказа переоткрыто, а не переиспользовано


def test_retries_are_limited_and_error_surfaces():
    script = [_grouped(_http_error(403))] * mcp_client.RETRY_ATTEMPTS
    session, _ = _session_over(script)
    with pytest.raises(BaseException):
        asyncio.run(session.call_tool("get_content", {"articleId": "a-1"}))


def test_permanent_error_is_not_retried():
    """401 — это отозванный токен, а не икота защиты: повторять нечего."""
    session, state = _session_over([_grouped(_http_error(401)), _ok_result()])
    with pytest.raises(BaseException):
        asyncio.run(session.call_tool("get_content", {"articleId": "a-1"}))
    assert state["opened"] == 1


def test_one_connection_serves_several_calls():
    """Каждое открытие соединения стоит трёх HTTP-запросов к Базе Знаний —
    именно их плотность и ловит защита, поэтому вызовы идут в одном соединении."""
    session, state = _session_over([_ok_result(), _ok_result(), _ok_result()])

    async def scenario():
        for _ in range(3):
            await session.call_tool("get_content", {"articleId": "a-1"})

    asyncio.run(scenario())
    assert state["opened"] == 1
    assert len(state["client"].calls) == 3


def test_cause_hidden_behind_cancellation_is_still_retried():
    """Под блокировкой запрос не падает с 403 напрямую: MCP держит соединение в
    своей task group, она отменяет ожидающий вызов, и наружу выходит
    CancelledError. Настоящая причина всплывает только при закрытии соединения —
    проверено смоуком на сервере, где первая версия ретрая из-за этого не сработала.
    """
    session = mcp_client.Session()
    state = {"opened": 0, "client": None}
    remaining = [asyncio.CancelledError(), _ok_result()]

    async def fake_open(self):
        state["opened"] += 1
        state["client"] = _FakeClient(remaining)
        # Закрытие оборванного соединения отдаёт настоящую причину — 403 от защиты.
        stack = types.SimpleNamespace(
            aclose=_raising_aclose if state["opened"] == 1 else _clean_aclose
        )
        return stack, state["client"]

    session._open = types.MethodType(fake_open, session)
    result = asyncio.run(session.call_tool("get_content", {"articleId": "a-1"}))
    assert '"ok": true' in result
    assert state["opened"] == 2


async def _raising_aclose():
    raise _grouped(_http_error(403))


async def _clean_aclose():
    return None


def test_real_cancellation_is_not_mistaken_for_the_shield():
    """Отмена без транзиентной причины — это настоящая отмена задачи
    (снятие хендлера, таймаут), её повторять нельзя."""
    session = mcp_client.Session()
    state = {"opened": 0}

    async def fake_open(self):
        state["opened"] += 1
        return types.SimpleNamespace(aclose=_clean_aclose), _FakeClient([asyncio.CancelledError()])

    session._open = types.MethodType(fake_open, session)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(session.call_tool("get_content", {"articleId": "a-1"}))
    assert state["opened"] == 1


def test_tool_list_is_retried_too():
    """Список инструментов запрашивается перед первым вопросом и своим отдельным
    соединением — под блокировкой он падал раньше, чем дело доходило до поиска,
    и валил весь ответ (найдено смоуком на сервере)."""
    session = mcp_client.Session()
    state = {"opened": 0}
    listed = types.SimpleNamespace(tools=[])

    class _Listing(_FakeClient):
        async def list_tools(self):
            item = self._script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

    remaining = [_grouped(_http_error(403)), listed]

    async def fake_open(self):
        state["opened"] += 1
        return types.SimpleNamespace(aclose=_clean_aclose), _Listing(remaining)

    session._open = types.MethodType(fake_open, session)
    assert asyncio.run(session.list_tools()) is listed
    assert state["opened"] == 2
