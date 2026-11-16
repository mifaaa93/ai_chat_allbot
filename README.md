# AI Chat Telegram-бот

ИИ-бот в Telegram: текст, голос, картинки, файлы, веб, генерация картинок и документов.

Репозиторий: https://github.com/mifaaa93/ai_chat_allbot

Сервер (тот же, что у бота-загрузчика видео): `root@77.73.135.108`, каталог `/opt/ai_chat_allbot`, systemd `ai_chat_allbot.service`.

`.env` на сервер кладётся один раз и при обновлении **не перезаписывается**.

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519_sf -o IdentitiesOnly=yes root@77.73.135.108
```

## Первый запуск на сервере

```bash
apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg git
git clone https://github.com/mifaaa93/ai_chat_allbot.git /opt/ai_chat_allbot
cd /opt/ai_chat_allbot
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env   # TELEGRAM_BOT_TOKEN и CVC_API_KEY
cp deploy/ai_chat_allbot.service /etc/systemd/system/ai_chat_allbot.service
systemctl daemon-reload
systemctl enable --now ai_chat_allbot.service
systemctl status ai_chat_allbot.service
```

## Запуск

```bash
systemctl start ai_chat_allbot.service
```

## Остановка

```bash
systemctl stop ai_chat_allbot.service
```

## Перезапуск

```bash
systemctl restart ai_chat_allbot.service
```

## Статус и логи

```bash
systemctl status ai_chat_allbot.service
journalctl -u ai_chat_allbot.service -n 50 --no-pager -f
tail -n 50 /opt/ai_chat_allbot/data/bot.log
```

## Обновление через GitHub

На компьютере:

```powershell
cd D:\code_26\IvanBots\ai_chat_allbot
git add -A
git commit -m "описание"
git push origin main
```

На сервере:

```bash
systemctl stop ai_chat_allbot.service
cd /opt/ai_chat_allbot
git pull --ff-only
.venv/bin/pip install -r requirements.txt
systemctl start ai_chat_allbot.service
systemctl status ai_chat_allbot.service
```

Если unit-файл менялся:

```bash
cp /opt/ai_chat_allbot/deploy/ai_chat_allbot.service /etc/systemd/system/ai_chat_allbot.service
systemctl daemon-reload
systemctl restart ai_chat_allbot.service
```

## Локально

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py
```

Команды бота: `/start` `/help` `/settings` `/new`
