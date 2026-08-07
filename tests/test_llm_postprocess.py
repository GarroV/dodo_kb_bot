"""Постобработка ответа модели: ссылки, разметка, язык.

Здесь исторически было две регрессии подряд (вырезались настоящие ссылки из
статей; не совпадала схема http/https), поэтому покрытие важнее всего именно тут.
"""
import llm

KB = "https://knowledgebase.dodois.io/next/article/space-1/article-1"


def test_keeps_knowledge_base_link():
    assert KB in llm._sanitize_links(f"Смотри статью: {KB}", "")


def test_drops_invented_link():
    out = llm._sanitize_links("Смотри: https://your-link-here.com", "")
    assert "your-link-here.com" not in out


def test_keeps_link_that_came_from_article_text():
    tool_output = "Домашней страницей сделайте http://tvboards.dodois.io/."
    out = llm._sanitize_links("Стартовая страница: https://tvboards.dodois.io", tool_output)
    assert "tvboards.dodois.io" in out


def test_scheme_and_trailing_slash_are_not_a_difference():
    assert llm._is_allowed_link("https://tvboards.dodois.io", "http://tvboards.dodois.io/")
    assert llm._is_allowed_link("http://tvboards.dodois.io/", "https://tvboards.dodois.io")


def test_markdown_link_becomes_plain_text_with_url():
    out = llm._sanitize_links(f"[Настройка касс]({KB})", "")
    assert "Настройка касс" in out and KB in out


def test_markdown_link_with_invented_url_keeps_only_label():
    out = llm._sanitize_links("[Статья](https://evil.example/x)", "")
    assert "Статья" in out and "evil.example" not in out


def test_headers_and_emphasis_are_stripped():
    out = llm._to_plain_text("### Заголовок\n\nразмер **650 КБ**, формат `JPG`")
    assert "#" not in out and "*" not in out and "`" not in out
    assert "650 КБ" in out


def test_blank_lines_are_collapsed():
    assert "\n\n\n" not in llm._to_plain_text("а\n\n\n\n\nб")


def test_labels_are_translated_to_answer_language():
    ru_mixed = "Articles:\n\nСтатья\nLink: " + KB
    assert "Статьи:" in llm._normalize_labels(ru_mixed, "ru")
    assert "Ссылка:" in llm._normalize_labels(ru_mixed, "ru")

    en_mixed = "Статьи:\n\nArticle\nСсылка: " + KB
    assert "Articles:" in llm._normalize_labels(en_mixed, "en")
    assert "Link:" in llm._normalize_labels(en_mixed, "en")


def test_labels_inside_line_are_not_touched():
    # Подпись заменяется только в начале строки, чтобы не искажать текст статьи.
    text = "в статье есть Ссылка: на приложение"
    assert llm._normalize_labels(text, "en") == text


def test_lang_detection():
    assert llm.lang_of("настройка кассы") == "ru"
    assert llm.lang_of("how to set up a till") == "en"
    assert llm.lang_of("PayU setup для Сербии") == "ru"
    assert llm.lang_of(None, "ru-RU") == "ru"
    assert llm.lang_of(None, "en-GB") == "en"
    assert llm.lang_of(None, None) == "en"
