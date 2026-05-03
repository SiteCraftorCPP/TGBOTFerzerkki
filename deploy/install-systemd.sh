#!/usr/bin/env bash
# Установка unit-файла systemd. Запуск из корня репозитория:
#   cd ~/bots/tgbot-ferzerkki && sudo bash deploy/install-systemd.sh
# Или с явным путём:
#   sudo bash deploy/install-systemd.sh /root/bots/tgbot-ferzerkki
#
# Пользователь процесса: по умолчанию $SUDO_USER (если вызвал через sudo из обычного юзера),
# иначе root. Переопределение: RUN_AS=myuser sudo bash deploy/install-systemd.sh

set -euo pipefail

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Нужны права root: sudo bash deploy/install-systemd.sh [ABS_OR_REL_PATH]"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_DIR="$(realpath "${1:-$REPO_ROOT}")"

if [[ ! -f "${INSTALL_DIR}/.venv/bin/python" ]]; then
  echo "Нет ${INSTALL_DIR}/.venv/bin/python — сначала venv и pip install -e ."
  exit 1
fi

RUN_AS="${RUN_AS:-${SUDO_USER:-root}}"
if [[ -z "${RUN_AS}" ]]; then
  RUN_AS=root
fi

UNIT=/etc/systemd/system/tgbot-ferzerkki.service

cat >"${UNIT}" <<EOF
[Unit]
Description=TGBOTFerzerkki Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_AS}
Group=${RUN_AS}
WorkingDirectory=${INSTALL_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${INSTALL_DIR}/.venv/bin/python -m app.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "${UNIT}"
systemctl daemon-reload
echo "Записано: ${UNIT}"
echo "  User/Group: ${RUN_AS}"
echo "  WorkingDirectory: ${INSTALL_DIR}"
echo "Включить и запустить:"
echo "  systemctl enable --now tgbot-ferzerkki"
echo "Логи:"
echo "  journalctl -u tgbot-ferzerkki -f"
