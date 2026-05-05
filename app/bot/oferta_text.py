"""Текст публичной оферты (app/bot/oferta_official.txt), нарезка под лимит Telegram."""

from pathlib import Path

_MAX_CHUNK = 3900

OFERTA_ACCEPT_CB = "oferta:accept"


def load_oferta_raw() -> str:
    path = Path(__file__).resolve().parent / "oferta_official.txt"
    return path.read_text(encoding="utf-8")


def iter_oferta_chunks() -> list[str]:
    text = load_oferta_raw()
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        sep = "\n\n" if cur else ""
        candidate = f"{cur}{sep}{p}"
        if len(candidate) <= _MAX_CHUNK:
            cur = candidate
            continue
        if cur:
            chunks.append(cur)
        if len(p) <= _MAX_CHUNK:
            cur = p
        else:
            for i in range(0, len(p), _MAX_CHUNK):
                chunks.append(p[i : i + _MAX_CHUNK])
            cur = ""
    if cur:
        chunks.append(cur)
    return chunks
