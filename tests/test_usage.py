"""Учёт транзакций и расчёт стоимости.

Кэшированный вход стоит на порядок дешевле обычного, поэтому считать его по
общей ставке нельзя — оценка завышается в разы.
"""
import json

import pytest

import config
import usage


@pytest.fixture()
def usage_file(tmp_path, monkeypatch):
    path = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_FILE", str(path))
    return path


def test_cached_input_is_cheaper_than_fresh():
    fresh_only = usage.estimate_cost("gpt-5.6-luna", 10_000, 0, 0)
    all_cached = usage.estimate_cost("gpt-5.6-luna", 10_000, 10_000, 0)
    assert all_cached == pytest.approx(fresh_only / 10)


def test_cost_matches_price_table():
    # 20k свежего входа, 10k из кэша, 1k выхода на luna ($0.20 / $0.02 / $1.20 за 1M)
    cost = usage.estimate_cost("gpt-5.6-luna", 30_000, 10_000, 1_000)
    expected = (20_000 * 0.20 + 10_000 * 0.02 + 1_000 * 1.20) / 1e6
    assert cost == pytest.approx(expected)


def test_unknown_model_costs_zero_instead_of_guessing():
    assert usage.estimate_cost("model-which-does-not-exist", 10_000, 0, 1_000) == 0.0


def test_record_writes_cost_and_cached_tokens(usage_file):
    usage.record(
        telegram_id=1, user_name="Тест", model="gpt-5.6-luna",
        prompt_tokens=1_000, completion_tokens=100, total_tokens=1_100,
        rounds=2, ok=True, cached_prompt_tokens=500,
    )
    entry = json.loads(usage_file.read_text(encoding="utf-8").strip())
    assert entry["cached_prompt_tokens"] == 500
    assert entry["cost_usd"] > 0


def test_summarize_empty_file(usage_file):
    stats = usage.summarize()
    assert stats["transactions"] == 0
    assert stats["cost_usd"] == 0.0


def test_summarize_aggregates_by_user(usage_file):
    for name, ok in [("Аня", True), ("Аня", True), ("Боб", False)]:
        usage.record(
            telegram_id=1, user_name=name, model="gpt-5.6-luna",
            prompt_tokens=1_000, completion_tokens=100, total_tokens=1_100,
            rounds=1, ok=ok, cached_prompt_tokens=100,
        )
    stats = usage.summarize()
    assert stats["transactions"] == 3
    assert stats["failed"] == 1
    assert stats["by_user"]["Аня"]["transactions"] == 2
    assert stats["cached_tokens"] == 300


def test_summarize_backfills_cost_for_old_records(usage_file):
    # Записи, сделанные до появления cost_usd, не должны занижать общую сумму.
    old = {
        "ts": 1, "telegram_id": 1, "user_name": "Аня", "model": "gpt-5.6-luna",
        "prompt_tokens": 10_000, "completion_tokens": 500, "total_tokens": 10_500,
        "rounds": 2, "ok": True,
    }
    usage_file.write_text(json.dumps(old, ensure_ascii=False) + "\n", encoding="utf-8")
    assert usage.summarize()["cost_usd"] > 0


def test_summarize_skips_broken_lines(usage_file):
    usage_file.write_text("не JSON\n", encoding="utf-8")
    assert usage.summarize()["transactions"] == 0


def test_records_chat_so_usage_can_be_audited_later(usage_file):
    usage.record(
        telegram_id=1, user_name="Аня", model="gpt-5.6-luna",
        prompt_tokens=1_000, completion_tokens=100, total_tokens=1_100,
        rounds=1, ok=True, cached_prompt_tokens=0,
        chat_id=-1001, chat_title="Сербия — партнёры",
    )
    entry = json.loads(usage_file.read_text(encoding="utf-8").strip())
    assert entry["chat_id"] == -1001
    assert entry["chat_title"] == "Сербия — партнёры"


def test_summarize_groups_by_chat(usage_file):
    for chat_id, title in [(-1001, "Сербия"), (-1001, "Сербия"), (-1002, "Казахстан")]:
        usage.record(
            telegram_id=1, user_name="Аня", model="gpt-5.6-luna",
            prompt_tokens=1_000, completion_tokens=100, total_tokens=1_100,
            rounds=1, ok=True, cached_prompt_tokens=0,
            chat_id=chat_id, chat_title=title,
        )
    by_chat = usage.summarize()["by_chat"]
    assert by_chat["Сербия (-1001)"]["transactions"] == 2
    assert by_chat["Казахстан (-1002)"]["transactions"] == 1


def test_old_records_without_chat_are_skipped_in_chat_breakdown(usage_file):
    # Записи до появления chat_id не должны ломать разбивку по чатам.
    old = {
        "ts": 1, "telegram_id": 1, "user_name": "Аня", "model": "gpt-5.6-luna",
        "prompt_tokens": 1_000, "completion_tokens": 100, "total_tokens": 1_100,
        "rounds": 1, "ok": True,
    }
    usage_file.write_text(json.dumps(old, ensure_ascii=False) + "\n", encoding="utf-8")
    stats = usage.summarize()
    assert stats["transactions"] == 1
    assert stats["by_chat"] == {}
