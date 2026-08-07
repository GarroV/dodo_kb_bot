"""Гейт группового чата: на что бот реагирует, а что молча игнорирует."""
import group_gate


def test_ignores_partner_chatter():
    assert not group_gate.gate_group_text("Привет, как дела с поставками?", "dodo_kb_bot", False).process


def test_processes_mention_and_strips_it():
    verdict = group_gate.gate_group_text("@dodo_kb_bot как настроить кассу", "dodo_kb_bot", False)
    assert verdict.process
    assert verdict.text == "как настроить кассу"


def test_processes_mention_in_the_middle():
    verdict = group_gate.gate_group_text("коллеги, @dodo_kb_bot подскажет", "dodo_kb_bot", False)
    assert verdict.process
    assert "@dodo_kb_bot" not in verdict.text


def test_mention_is_case_insensitive():
    assert group_gate.gate_group_text("@Dodo_KB_Bot вопрос", "dodo_kb_bot", False).process


def test_another_bot_mention_is_ignored():
    assert not group_gate.gate_group_text("@dodo_constr_bot статус", "dodo_kb_bot", False).process


def test_similar_username_is_not_a_match():
    # @dodo_kb_bot2 — другой бот, границы слова должны это различать.
    assert not group_gate.gate_group_text("@dodo_kb_bot2 вопрос", "dodo_kb_bot", False).process


def test_reply_to_bot_works_without_mention():
    verdict = group_gate.gate_group_text("а для Сербии?", "dodo_kb_bot", is_reply_to_bot=True)
    assert verdict.process
    assert verdict.text == "а для Сербии?"


def test_empty_text_is_ignored():
    assert not group_gate.gate_group_text("   ", "dodo_kb_bot", False).process
    assert not group_gate.gate_group_text(None, "dodo_kb_bot", False).process


def test_unknown_own_username_does_not_crash():
    # До ответа getMe username неизвестен: упоминание распознать нельзя, но и падать нельзя.
    assert not group_gate.gate_group_text("@dodo_kb_bot вопрос", None, False).process
