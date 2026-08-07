"""Справка в коде и её копия в docs/ не должны расходиться.

Текст /kb_info живёт в main.TEXTS["info"], а docs/PARTNER_GUIDE.md — читаемая
копия для тех, кто не запускает бота. Копия уже успевала устареть (обещала
партнёрам не тот способ обращения), поэтому расхождение ловим тестом, а не
дисциплиной.
"""
import pathlib
import re

import main

GUIDE = pathlib.Path(__file__).resolve().parent.parent / "docs" / "PARTNER_GUIDE.md"
BLOCKS = {"ru": "Русская версия", "en": "English version"}


def _normalized(text: str) -> str:
    """Перенос строк в Markdown — вопрос вёрстки, а не содержания."""
    return " ".join(text.split())


def _guide_block(header: str) -> str:
    m = re.search(rf"## {header}\n\n```\n(.*?)```", GUIDE.read_text(encoding="utf-8"), re.S)
    assert m, f"в {GUIDE.name} нет блока «{header}»"
    return m.group(1)


def test_guide_has_both_languages():
    for header in BLOCKS.values():
        assert _guide_block(header).strip()


def test_guide_matches_code():
    for lang, header in BLOCKS.items():
        assert _normalized(_guide_block(header)) == _normalized(main.TEXTS["info"][lang]), (
            f"docs/PARTNER_GUIDE.md ({lang}) расходится с main.TEXTS['info'][{lang!r}]"
        )
