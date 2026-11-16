# CheapVibeCode Telegram chatter — рабочий план

Заказчик: Alex TN. Продукт: ИИ-чат в Telegram «как ChatGPT/Claude» на API CheapVibeCode.
Видео смотреть не надо. Генерация видео — опционально, не блокер v1.

## Цель v1

Личный/командный чаттер в Telegram:

- текст, голос, картинки, файлы
- выбор модели
- красивые ответы (Rich Message)
- без лагов в переписке
- умеет смотреть веб и отдавать сгенерированные файлы

Ключ API и токен бота придут отдельно. До этого — каркас, моки, юнит-тесты.

## Что сознательно не делаем в v1

- TTS: у провайдера нет `audio/speech`
- Понимание видео (vision по роликам)
- Генерация видео Kling/MiniMax — фаза 2
- Мультиаккаунт / биллинг пользователей / рефералка
- Стриминг токенов в Telegram (мельтешение и лаги)

## Стек

Как соседние боты Ивана:

- Python 3.12+, aiogram 3
- CheapVibeCode `https://ru.cheapvibecode.ru/v1` (fallback `cheapvibecode.ru`)
- SQLite на чат/историю/настройки
- ffmpeg → WAV для STT (`codex-transcribe`, лимит 25 MiB)
- `curl_cffi` (Chrome impersonate) для веба
- Rich Message: `InputRichMessage` + markdown, fallback на plain text
- systemd + venv на сервере позже

Паттерны: `bayer_stat` (CVC chat, voice, rich edit, retry), `market_news` (curl_cffi, rich HTML).

## UX, чтобы не лагало

1. Сразу `sendChatAction` typing + одно статус-сообщение («Думаю…» / «Слушаю голос…» / «Качаю файл…»).
2. Стрим CVC внутри процесса. В Telegram — одна финальная правка статус-сообщения в Rich Message. Не слать чанки.
3. Per-chat очередь: пока идёт ответ, новые сообщения копятся и уходят следующей пачкой. AsyncTeleBot, LLM в `asyncio.to_thread`. 429 ждёт Retry-After (до 120 с, до 5 повторов), 5xx/timeout — 2 повтора.
4. Retry только 429/502/503/504, с `Retry-After`. 4xx без ретрая, понятная ошибка.
5. Таймауты: STT 60s, chat 120s, image 180s, web 20s.
6. История: последние N сообщений + суммаризация при переполнении контекста. Новый диалог — кнопка.
7. Длинный ответ: резать по лимиту rich (32k) на части, не ронять сообщение.

## Поведение как у ChatGPT/Claude

Сообщение пользователя → нормализация входа → tools (по необходимости) → ответ моделью → доставка.

Входы:

| Telegram | Что делаем |
|---|---|
| текст | как есть |
| voice / audio | ffmpeg WAV → `POST /v1/audio/transcriptions` `codex-transcribe`, показать распознанный текст мелкой пометкой, дальше как текст |
| фото / сжатое фото | vision: `image_url` data URL в chat/completions |
| документ-картинка | то же |
| PDF / txt / md / csv / json / docx | текст вытащить локально; PDF лучше слать в Gemini (input pdf) или извлекать |
| ссылка | tool `web_fetch` через curl_cffi |

Выходы:

- основной ответ — Rich Message (заголовки, списки, код, жирный)
- картинка по запросу — `POST /v1/images/generations` (`gpt-image-2.5-flare`, quality low по умолчанию) + вложение в rich или отдельный photo
- файл (скрипт, csv, md, json, xlsx) — `send_document`, не пихать простыню в чат
- если модель вернула markdown-файл в tool — сохранить и отдать документом

Настройки (`/settings` + инлайн):

- модель (группы: Быстрые / Сильные / Claude / GPT / Gemini / Китайские)
- глубина reasoning: off / low / medium / high / xhigh / max (не все модели принимают верхние уровни)
- новый чат
- качество картинок: low / medium / high
- системный стиль: обычный / краткий / код

Дефолт модели: `gpt-6-luna` (дешёвая, vision). Для файлов PDF — автопереключение на `gemini-3.8-flash` или явное предупреждение.

## Tools модели

Минимальный набор, без зоопарка:

1. `web_fetch(url)` — curl_cffi, Chrome JA3, лимит ~80KB текста, вычистить HTML в markdown. Только http(s).
2. `web_search(query)` — один поисковый HTML (DuckDuckGo/Brave) через curl_cffi, 5 ссылок, потом fetch по выбору модели.
3. `generate_image(prompt, size=auto, quality=low)` — CVC images API.
4. `write_file(filename, content, kind)` — собрать документ и отдать пользователю.

Web search hosted у CVC не используем как основу: заказчику нужен curl_cffi, плюс hosted search зависит от модели.

## Эндпоинты CVC, которые трогаем

- `POST /v1/chat/completions` — основной диалог, vision, tools, stream
- `POST /v1/audio/transcriptions` — голос
- `POST /v1/images/generations` (+ edits, если пользователь прислал фото «перерисуй»)
- `GET /v1/models` — кэш каталога раз в час для меню
- `GET /v1/balance` — в `/settings` для админа, не светить всем

Не трогаем в v1: `/videos/*`, Anthropic `/messages`, Codex backend.

## Структура репо

```
ai_chat_allbot/
  bot/
    main.py            # polling, handlers
    handlers_chat.py
    handlers_settings.py
    media.py           # voice, photos, docs
    rich.py            # markdown → InputRichMessage + fallback
    delivery.py        # status msg, lock, edit
  llm/
    client.py          # OpenAI-compatible CVC, retry, stream collect
    tools.py
    web.py             # curl_cffi fetch/search
    images.py
    transcribe.py
  db.py
  models_catalog.py    # whitelist + human names + modalities
  config.py            # env: BOT_TOKEN, CVC_API_KEY, CVC_BASE_URL, ALLOWED_USER_IDS
  tests/
  requirements.txt
  .env.example
  PLAN.md
```

Секреты только в `.env`, gitignore.

## Доступ

`ALLOWED_USER_IDS` (пусто = только владелец после первого `/start` или закрытый бот). Пока заказчик не сказал «для всех» — whitelist.

## Красивые ответы

- Системный промпт: коротко, по делу, markdown, код в блоках, не лить дисклеймеры.
- `InputRichMessage(markdown=...)` как в bayer_stat; если Telegram отверг — plain.
- Код длиннее ~2–3 экранов → файл `.py`/`.md`.
- Не слать «как ИИ-модель я…».

## Тесты до ключей

- нормализация markdown → rich
- выбор модели / modalities (vision vs text-only)
- tool schemas
- web_fetch: html → text, отказ на file:// и огромные ответы
- transcribe: мок HTTP, ffmpeg путь
- per-chat lock
- retry policy

После ключей: живой `/start`, текст, голос, фото, генерация картинки, ссылка, файл.

## Порядок работ

1. Каркас: config, db (users, threads, messages), polling, `/start` `/settings` `/new`.
2. CVC chat + история + rich delivery + lock + retry.
3. Голос (ffmpeg + transcribe).
4. Входные фото/файлы.
5. Tools: web_fetch/search, generate_image, write_file.
6. Меню моделей из каталога.
7. Полировка UX (статусы, обрезка, ошибки).
8. Живые тесты по ключам заказчика.
9. Фаза 2: video generations, image edits, PDF-native Gemini.

## Риски

- Rich Message API ещё сырой: всегда fallback.
- Telegram voice = OGG/Opus, CVC STT = WAV.
- Vision-модели не все; text-only нельзя кормить картинкой.
- Картинки списывают 50–150k токенов за штуку.
- curl_cffi нужен impersonate, обычный requests часто режут.
- Баланс CVC у кабинета сейчас может быть нулевой — тесты упрутся в оплату.
