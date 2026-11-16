# CheapVibeCode Telegram chatter

ИИ-чат в Telegram на API CheapVibeCode: текст, голос, картинки, файлы, веб, генерация картинок и документов.

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

Команды: `/start` `/settings` `/new`

Пока модель отвечает, следующие сообщения чата копятся и уходят следующей пачкой. Другие пользователи не ждут: `AsyncTeleBot`, LLM в потоках. Параллельность не режем: при 429 ждём `Retry-After`.
