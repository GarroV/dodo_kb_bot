# Справка для партнёров

Этот текст бот выдаёт по команде `/kb_info`; источник — `main.TEXTS["info"]`,
править нужно там, а файл держать в соответствии.

## Русская версия

```
Бот Базы Знаний (@dodo_kb_bot) — отвечает на вопросы по Базе Знаний Dodo.

Как спросить в этом чате:
/kb_ask как настроить кассу ресторана

Что придёт: короткий ответ по существу и ссылки на статьи, за 10–20 секунд.
Отвечает на языке вопроса и только по Базе Знаний — если материала нет, скажет
прямо.

Советы: один конкретный вопрос за раз; называйте страну («в Сербии»); каждый
вопрос формулируйте целиком — предыдущие сообщения бот не помнит.

Бот не читает сообщения группы и реагирует только на команду. По этой же
причине не срабатывает упоминание через собаку — обращайтесь через /kb_ask.
```

## English version

```
Knowledge Base bot (@dodo_kb_bot) — answers questions from the Dodo Knowledge
Base.

How to ask in this chat:
/kb_ask how to configure the restaurant cash register

What you get: a short answer plus links to the source articles, in 10–20
seconds. It replies in the language of your question and only from the Knowledge
Base — if there is nothing on the topic, it says so.

Tips: ask one specific question at a time; name the country ("in Serbia"); make
each question self-contained — the bot doesn't remember previous messages.

The bot does not read the group's messages and only reacts to the command. For
the same reason an @mention does not work — use /kb_ask.
```

Язык выбирается по `language_code` профиля Telegram того, кто вызвал команду.

В справке намеренно указан только `/kb_ask`: `@упоминание` до бота не доходит,
пока включён Group Privacy Mode (см. README), а обещать партнёрам нерабочий
способ нельзя. Когда privacy отключат и бота заново добавят в чат — добавить в
`main.TEXTS["info"]` строку с упоминанием.
