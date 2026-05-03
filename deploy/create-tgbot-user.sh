#!/bin/sh
# Однократно на VPS: создаёт системного пользователя без логина (опционально).
set -e
if ! id tgbot >/dev/null 2>&1; then
  sudo useradd --system --home /opt/TGBOTFerzerkki --shell /usr/sbin/nologin tgbot
  echo "Создан пользователь tgbot"
else
  echo "Пользователь tgbot уже есть"
fi
