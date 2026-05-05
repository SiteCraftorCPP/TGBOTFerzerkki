from urllib.parse import quote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    # Несколько админов: telegram_id через запятую, без пробелов или с пробелами (обрежутся).
    admin_ids: str = ""
    telegram_proxy: str | None = None
    moderation_chat_id: str | None = None
    # Подтема форума: все алерты о спорах в одну ветку. Пусто — для каждого спора создаётся новая тема (как тикет).
    moderation_disputes_thread_id: str | None = None
    database_url: str = "sqlite+aiosqlite:///./clashduel.db"
    subscription_price_rub: int = 150
    default_commission_percent: int = 15
    subscriber_commission_percent: int = 5
    reset_support_tickets_on_startup: bool = Field(
        default=False,
        description="Только SQLite: при true удаляет все обращения и сбрасывает нумерацию при старте бота.",
    )
    # Смени значение, чтобы все пользователи снова увидели оферту.
    oferta_version: str = "1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def admin_ids_list(self) -> list[int]:
        """Числовые Telegram user id. Запятая / точка с запятой, пробелы, комментарий # после id."""
        result: list[int] = []
        raw = (self.admin_ids or "").replace(";", ",")
        for part in raw.split(","):
            s = part.strip()
            if not s or s.startswith("#"):
                continue
            s = s.split("#", 1)[0].strip()
            if not s:
                continue
            result.append(int(s))
        return result

    @property
    def moderation_chat_id_int(self) -> int | None:
        raw = (self.moderation_chat_id or "").strip()
        if not raw:
            return None
        return int(raw)

    @property
    def moderation_disputes_thread_id_int(self) -> int | None:
        raw = (self.moderation_disputes_thread_id or "").strip()
        if not raw:
            return None
        return int(raw)

    @property
    def telegram_proxy_url(self) -> str | None:
        raw = (self.telegram_proxy or "").strip()
        if not raw:
            return None
        if "://" in raw:
            return raw

        parts = raw.split(":")
        if len(parts) == 4:
            host, port, user, password = parts
            return f"socks5://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
        return raw


def get_settings() -> Settings:
    """Читает .env при каждом вызове (без кэша): актуальный MODERATION_CHAT_ID и др. из файла."""
    return Settings()

