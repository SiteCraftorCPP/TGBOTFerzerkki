"""Ресурсы оферты: колбэк и путь к .docx в каталоге пакета."""

from pathlib import Path

OFERTA_ACCEPT_CB = "oferta:accept"
OFERTA_DOCX_NAME = "oferta_public_offer.docx"


def oferta_docx_path() -> Path:
    return Path(__file__).resolve().parent / OFERTA_DOCX_NAME
