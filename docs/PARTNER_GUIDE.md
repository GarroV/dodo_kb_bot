# Справка для партнёров

Этот же текст бот выдаёт по команде `/kb_info` — она берёт его из
`main.TEXTS["info"]`, так что править нужно там, а этот файл держать в
соответствии.

## Русская версия

```
Dodo KB — бот по Базе Знаний Dodo.

Как спросить (в этом чате):
• @dodo_kb_bot как настроить кассу ресторана
• /kb_ask как настроить кассу ресторана
• реплай на любое сообщение бота

Что придёт: короткий ответ по существу и ссылки на статьи, за 10–20 секунд.
Отвечает на языке вопроса и только по Базе Знаний — если материала нет, скажет
прямо.

Советы: один конкретный вопрос за раз; называйте страну («в Сербии»); каждый
вопрос формулируйте целиком — предыдущие сообщения бот не помнит.
```

## English version

```
Dodo KB — the Dodo Knowledge Base bot.

How to ask (in this chat):
• @dodo_kb_bot how long can dough balls be stored?
• /kb_ask how long can dough balls be stored?
• reply to any message from the bot

What you get: a short answer plus links to the source articles, in 10–20
seconds. It replies in the language of your question and only from the Knowledge
Base — if there is nothing on the topic, it says so.

Tips: ask one specific question at a time; name the country ("in Serbia"); make
each question self-contained — the bot doesn't remember previous messages.
```

Язык выбирается по `language_code` профиля Telegram того, кто вызвал команду.

`@упоминание` требует выключенного Group Privacy Mode (см. README) — `/kb_ask`
и реплай работают в любом случае.
