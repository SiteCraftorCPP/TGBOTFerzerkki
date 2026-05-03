from app.core.config import Settings


def test_admin_ids_list_accepts_comma_separated() -> None:
    settings = Settings(telegram_bot_token="t", admin_ids="111, 222 , 333")
    assert settings.admin_ids_list == [111, 222, 333]


def test_proxy_panel_format_is_normalized() -> None:
    settings = Settings(
        telegram_bot_token="token",
        telegram_proxy="154.81.199.66:64181:hGtcCsrT:S1mhartf",
    )

    assert settings.telegram_proxy_url == "socks5://hGtcCsrT:S1mhartf@154.81.199.66:64181"


def test_proxy_url_is_kept_as_is() -> None:
    settings = Settings(telegram_bot_token="token", telegram_proxy="http://user:pass@127.0.0.1:8080")

    assert settings.telegram_proxy_url == "http://user:pass@127.0.0.1:8080"

