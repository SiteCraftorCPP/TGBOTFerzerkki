#!/usr/bin/env python3
"""
Сброс обращений поддержки и счётчика (SQLite). Не требует CLI sqlite3.

  cd /path/to/tgbot-ferzerkki
  sudo systemctl stop tgbot-ferzerkki   # чтобы файл БД не был залочен
  ./.venv/bin/python deploy/reset_support_tickets.py
  sudo systemctl start tgbot-ferzerkki
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.core.config import Settings  # noqa: E402


def _sqlite_path(settings: Settings) -> Path:
    url = (settings.database_url or "").strip()
    if "sqlite" not in url:
        print("DATABASE_URL должен указывать на sqlite (как в .env).", file=sys.stderr)
        sys.exit(1)
    if "///" not in url:
        print(f"Не удалось разобрать путь из DATABASE_URL: {url}", file=sys.stderr)
        sys.exit(1)
    path_part = url.split("///", 1)[1].strip()
    p = Path(path_part)
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    return p


def main() -> None:
    settings = Settings()
    db_path = _sqlite_path(settings)
    if not db_path.is_file():
        print(f"Файл БД не найден: {db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"DELETE FROM support_tickets в {db_path}")
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.execute("DELETE FROM support_tickets")
        deleted = cur.rowcount
        con.commit()
        print(f"Удалено строк тикетов: {deleted}.")
        try:
            con.execute("DELETE FROM sqlite_sequence WHERE name='support_tickets'")
            con.commit()
            print("Счётчик sqlite_sequence для support_tickets сброшен.")
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
                print(
                    "Таблицы sqlite_sequence нет (обычно до первого AUTOINCREMENT) — это норма, "
                    "DELETE уже закоммичен."
                )
            else:
                raise
    finally:
        con.close()
    print("Готово.")


if __name__ == "__main__":
    main()
