"""Ограничение частоты и список разрешённых чатов."""
import config
import limits


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_first_question_passes():
    clock = FakeClock()
    th = limits.Throttle(user_cooldown_seconds=10, chat_hourly_limit=60, now=clock)
    assert th.check(user_id=1, chat_id=-100) is None


def test_second_question_too_soon_is_rejected():
    clock = FakeClock()
    th = limits.Throttle(user_cooldown_seconds=10, chat_hourly_limit=60, now=clock)
    th.check(1, -100)
    assert th.check(1, -100) == "cooldown"


def test_question_passes_after_cooldown():
    clock = FakeClock()
    th = limits.Throttle(user_cooldown_seconds=10, chat_hourly_limit=60, now=clock)
    th.check(1, -100)
    clock.advance(10)
    assert th.check(1, -100) is None


def test_cooldown_is_per_user():
    clock = FakeClock()
    th = limits.Throttle(user_cooldown_seconds=10, chat_hourly_limit=60, now=clock)
    th.check(1, -100)
    assert th.check(2, -100) is None


def test_rejection_does_not_extend_the_pause():
    # Иначе спам-кликер держал бы пользователя в блоке бесконечно.
    clock = FakeClock()
    th = limits.Throttle(user_cooldown_seconds=10, chat_hourly_limit=60, now=clock)
    th.check(1, -100)
    clock.advance(5)
    assert th.check(1, -100) == "cooldown"
    clock.advance(5)
    assert th.check(1, -100) is None


def test_chat_hourly_limit():
    clock = FakeClock()
    th = limits.Throttle(user_cooldown_seconds=0, chat_hourly_limit=3, now=clock)
    for i in range(3):
        assert th.check(user_id=i, chat_id=-100) is None
    assert th.check(user_id=99, chat_id=-100) == "chat_limit"


def test_hourly_window_slides():
    clock = FakeClock()
    th = limits.Throttle(user_cooldown_seconds=0, chat_hourly_limit=2, now=clock)
    th.check(1, -100)
    th.check(2, -100)
    assert th.check(3, -100) == "chat_limit"
    clock.advance(3601)
    assert th.check(3, -100) is None


def test_chat_limit_is_per_chat():
    clock = FakeClock()
    th = limits.Throttle(user_cooldown_seconds=0, chat_hourly_limit=1, now=clock)
    th.check(1, -100)
    assert th.check(1, -200) is None


def test_empty_allowlist_permits_any_chat(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_CHAT_IDS", frozenset())
    assert limits.is_chat_allowed(-100500)


def test_allowlist_blocks_other_chats(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_CHAT_IDS", frozenset({-100}))
    assert limits.is_chat_allowed(-100)
    assert not limits.is_chat_allowed(-200)


def test_allowlist_parsing_accepts_commas_and_spaces(monkeypatch):
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "-100, -200  -300")
    assert config._int_set("ALLOWED_CHAT_IDS") == frozenset({-100, -200, -300})


def test_allowlist_parsing_of_empty_value(monkeypatch):
    monkeypatch.setenv("ALLOWED_CHAT_IDS", "")
    assert config._int_set("ALLOWED_CHAT_IDS") == frozenset()
