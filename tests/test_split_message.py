"""Нарезка длинных ответов под лимит Telegram (4096 символов)."""
import main

KB = "https://knowledgebase.dodois.io/next/article/space-1/article-1"


def test_short_text_is_not_split():
    assert main._split_message("короткий ответ") == ["короткий ответ"]


def test_every_part_fits_the_limit():
    text = "\n".join(f"строка {i}" for i in range(500))
    parts = main._split_message(text, limit=200)
    assert len(parts) > 1
    assert all(len(p) <= 200 for p in parts)


def test_links_are_not_cut_in_half():
    # Ровно эта ошибка ломала ссылки: разрыв приходился на середину адреса.
    text = "\n".join([f"Статья {i}\nСсылка: {KB}" for i in range(20)])
    parts = main._split_message(text, limit=300)
    for part in parts:
        for line in part.splitlines():
            if "knowledgebase" in line:
                assert line.endswith("article-1")


def test_nothing_is_lost_when_splitting():
    text = "\n".join(f"строка {i}" for i in range(100))
    assert "\n".join(main._split_message(text, limit=120)) == text


def test_single_line_longer_than_limit_is_still_sent():
    long_line = "x" * 500
    parts = main._split_message(long_line, limit=100)
    assert len(parts) == 5
    assert "".join(parts) == long_line
