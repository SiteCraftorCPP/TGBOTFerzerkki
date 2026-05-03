# ClashDuel Bot

Локальный MVP Telegram-бота для матчей Clash Royale и Brawl Stars на внутренний баланс.

Репозиторий: https://github.com/SiteCraftorCPP/TGBOTFerzerkki

## Запуск

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Заполни `TELEGRAM_BOT_TOKEN` и `ADMIN_IDS` в `.env`, затем:

```powershell
python -m app.main
```

**Несколько админов:** в `.env` перечисли numeric Telegram ID через запятую, пробелы допустимы — обрежутся:
`ADMIN_IDS=111111111,222222222`

## VPS (git + systemd)

Чтобы не трогать другие проекты на сервере, положи бота в **отдельный каталог** (пример ниже — `~/bots/tgbot-ferzerkki`; можно `/srv/tgbot-ferzerkki` и т.п.). В `tgbot-ferzerkki.service` тогда замени `WorkingDirectory` и `ExecStart` на эти пути.

На сервере (Debian/Ubuntu):

```bash
mkdir -p ~/bots/tgbot-ferzerkki
cd ~/bots/tgbot-ferzerkki
git clone https://github.com/SiteCraftorCPP/TGBOTFerzerkki.git .
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
nano .env   # TOKEN, ADMIN_IDS, при необходимости MODERATION_CHAT_ID
```

Обновление уже установленного бота:

```bash
cd ~/bots/tgbot-ferzerkki
git pull
source .venv/bin/activate
pip install -e .
sudo systemctl restart tgbot-ferzerkki   # если сервис уже настроен
```

Альтернатива с `/opt` (как в юните по умолчанию):

```bash
sudo mkdir -p /opt/TGBOTFerzerkki
sudo chown "$USER:$USER" /opt/TGBOTFerzerkki
cd /opt/TGBOTFerzerkki
git clone https://github.com/SiteCraftorCPP/TGBOTFerzerkki.git .
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
nano .env   # TOKEN, ADMIN_IDS, при необходимости MODERATION_CHAT_ID
```

Юнит systemd (автоперезапуск при падении):

```bash
sudo cp deploy/tgbot-ferzerkki.service /etc/systemd/system/tgbot-ferzerkki.service
# Открой файл и выставь User=/WorkingDirectory= под свою установку
sudo systemctl daemon-reload
sudo systemctl enable --now tgbot-ferzerkki
journalctl -u tgbot-ferzerkki -f
```

Опционально системный пользователь без шелла: см. `deploy/create-tgbot-user.sh`, затем `chown -R tgbot:tgbot /opt/TGBOTFerzerkki`.

## Чат модерации (форум)

Создай супергруппу, включи **темы** (Topics), добавь бота админом с правом **управлять топиками**.  
Укажи ID группы в `.env` как `MODERATION_CHAT_ID=-100...`. Тогда каждое обращение в «Поддержка» создаёт **отдельную ветку**: в ней удобно вести диалог, а текст из ветки от имени админа уходит пользователю в ЛС.

Если `MODERATION_CHAT_ID` пустой — уведомления улетают staff в личку.

Споры можно собирать в одну подтему: `MODERATION_DISPUTES_THREAD_ID=...` (message_thread_id ветки «Споры»).

## Что уже есть

- Русское меню с профилем, играми, правилами, поддержкой, балансом и подпиской.
- SQLite-хранилище с автосозданием таблиц.
- Поддержка SOCKS/HTTP proxy для Telegram API.
- Матчи с блокировкой ставок, автоудалением через 3 минуты, результатами, спорами и комиссией.
- Служебная панель (только для staff): **`/admin`** — споры, тикеты, отмена матча, ручные корректировки баланса при необходимости.
- Платежи и вывод средств пока являются заглушками (у игрока — скоро оплата в разделе баланса).
