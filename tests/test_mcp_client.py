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
