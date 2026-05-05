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


def test_oferta_chunks_nonempty() -> None:
    from app.bot.oferta_text import iter_oferta_chunks

    chunks = iter_oferta_chunks()
    assert len(chunks) >= 1
    assert all(len(c) <= 4096 for c in chunks)
