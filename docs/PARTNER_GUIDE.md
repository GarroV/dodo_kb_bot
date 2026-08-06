# Бот Базы Знаний — инструкция для партнёров

Бот отвечает на вопросы по внутренней Базе Знаний Dodo: сам ищет статьи, читает
их и пересказывает главное со ссылками на источник. Логин и доступ к Базе Знаний
для этого не нужны.

## Как спросить

Бот работает **в групповом чате**, куда его добавили. В личных сообщениях
вопросы не принимаются.

Самый надёжный способ — команда:

```
/kb_ask как настроить кассу ресторана
```

Ещё можно **ответить реплаем** на любое сообщение бота — тогда команду писать
не нужно, просто задайте вопрос в реплае.

Упоминание в тексте (`@dodo_kb_bot ваш вопрос`) работает не во всех чатах: это
зависит от настройки бота в конкретном чате. Если на упоминание он молчит —
используйте `/kb_ask` или реплай.

Ответ занимает 10–20 секунд: сначала придёт «Ищу в Базе Знаний…», затем сам
ответ.

## Что придёт в ответе

1. Короткая суть — 2–4 строки по существу вопроса.
2. Список статей: название, о чём она, и ссылка на неё в Базе Знаний.

Всё, что бот пишет, взято из статей. Он не отвечает по памяти и не придумывает:
если по вопросу ничего не нашлось, он прямо об этом скажет.

## Язык

Отвечает на языке вопроса: спросили по-русски — ответ по-русски, спросили
по-английски — ответ по-английски. Названия статей приводятся так, как они
записаны в Базе Знаний (там есть и русские, и английские материалы).

## Как спрашивать, чтобы ответ был точнее

- **Называйте страну**, если вопрос про неё: «настройка кассы в Сербии». Тогда
  бот возьмёт материалы именно по этой стране, а если по ней ничего нет — скажет
  об этом, а не подсунет инструкцию для другой страны.
- **Широкий вопрос → обзор, узкий → шаги.** «Эквайринг для зарубежных стран»
  даст общую картину и от чего зависит выбор; «как подключить PayU через
  PaymentsOS» — конкретные шаги.
- **Каждый вопрос самостоятельный.** Бот не помнит предыдущие сообщения, поэтому
  вместо «а для Сербии?» повторите вопрос целиком: «настройка кассы в Сербии».
- Если ответ не по делу — переформулируйте, добавив термины из нужной области
  (например название системы или провайдера).

## Чего бот не делает

- Не меняет ничего в Базе Знаний — только чтение.
- Не заменяет поддержку: если ответа в Базе Знаний нет, вопрос нужно задать
  ответственной команде.

---

# Knowledge Base bot — partner guide

The bot answers questions about Dodo's internal Knowledge Base: it searches for
articles, reads them and sums up the key points with links to the source. You
don't need a Knowledge Base login for this.

## How to ask

The bot works **in a group chat** it has been added to. It doesn't take
questions in direct messages.

The most reliable way is the command:

```
/kb_ask how to configure the restaurant cash register
```

You can also **reply** to any of the bot's messages — no command needed, just
put your question in the reply.

An @mention in plain text (`@dodo_kb_bot your question`) doesn't work in every
chat — it depends on the bot's settings there. If it stays silent on a mention,
use `/kb_ask` or a reply.

An answer takes 10–20 seconds: first you'll get "Searching the Knowledge
Base…", then the answer itself.

## What you get

1. A short summary — 2–4 lines answering the question.
2. A list of articles: the title, what's inside, and a link to it in the
   Knowledge Base.

Everything the bot writes comes from the articles. It never answers from memory
and doesn't make things up: if nothing was found, it says so directly.

## Language

It replies in the language of your question — ask in English, get English. The
article titles stay as written in the Knowledge Base (it holds both Russian and
English materials).

## How to get more accurate answers

- **Name the country** if your question is about one: "cash register setup in
  Serbia". The bot will then use materials for that country, and if there are
  none, it will say so instead of handing you another country's instructions.
- **A broad question gets an overview, a narrow one gets steps.** "Acquiring for
  foreign countries" returns the big picture and what the choice depends on;
  "how to connect PayU via PaymentsOS" returns concrete steps.
- **Every question stands alone.** The bot doesn't remember previous messages,
  so instead of "and for Serbia?" repeat the whole question: "cash register
  setup in Serbia".
- If the answer misses the point, rephrase it with terms from the relevant area
  (a system or provider name, for example).

## What the bot doesn't do

- It never changes anything in the Knowledge Base — read-only access.
- It doesn't replace support: if the Knowledge Base has no answer, take the
  question to the responsible team.
