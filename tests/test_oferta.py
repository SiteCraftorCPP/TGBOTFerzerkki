import pytest

from app.db.models import User
from app.db.repositories import user_needs_oferta_acceptance


def test_user_needs_oferta_when_no_user() -> None:
    assert user_needs_oferta_acceptance(None, current_version="1") is True


def test_user_needs_oferta_when_version_mismatch() -> None:
    u = User(telegram_id=1, oferta_accepted_version="0")
    assert user_needs_oferta_acceptance(u, current_version="1") is True


def test_user_ok_when_version_matches() -> None:
    u = User(telegram_id=1, oferta_accepted_version="1")
    assert user_needs_oferta_acceptance(u, current_version="1") is False


def test_oferta_docx_bundled() -> None:
    from app.bot.oferta_text import oferta_docx_path

    p = oferta_docx_path()
    assert p.is_file()
    assert p.suffix.lower() == ".docx"
