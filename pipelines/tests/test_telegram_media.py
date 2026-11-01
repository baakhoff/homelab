"""Tests for pipelines/tools/telegram_media.py, on made-up messages. No
Telegram, no Telethon. Run from the repo root:

    uv run --with pytest pytest pipelines/tests
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import telegram_media  # noqa: E402


def _m(**kw):
    base = dict(id=7, date=datetime(2021, 6, 1, 10, 0, tzinfo=timezone.utc), media=SimpleNamespace(),
                photo=None, video=None, video_note=None, gif=None, sticker=None, document=None,
                file=SimpleNamespace(ext=".jpg", mime_type="image/jpeg", size=10))
    base.update(kw)
    return SimpleNamespace(**base)


def test_kind():
    assert telegram_media.kind(_m(photo=True)) == "photo"
    assert telegram_media.kind(_m(video=True)) == "video"
    assert telegram_media.kind(_m(video_note=True)) == "video"
    assert telegram_media.kind(_m(video=True, gif=True)) is None
    assert telegram_media.kind(_m(document=True, sticker=True)) is None
    assert telegram_media.kind(_m(document=True)) == "photo"  # an image sent as a file
    assert telegram_media.kind(_m(document=True, file=SimpleNamespace(ext=".mov", mime_type="video/quicktime", size=1))) == "video"
    assert telegram_media.kind(_m(document=True, file=SimpleNamespace(ext=".pdf", mime_type="application/pdf", size=1))) is None
    assert telegram_media.kind(_m(photo=True, media=SimpleNamespace(ttl_seconds=10))) is None
    assert telegram_media.kind(_m(media=None)) is None


def test_name(tmp_path):
    m = _m(photo=True)
    stem = telegram_media.stem_for(1, 2, m)
    assert stem.startswith("TG_20210601_120000_")  # Copenhagen, summer time
    assert stem == telegram_media.stem_for(1, 2, m) != telegram_media.stem_for(1, 3, m)
    assert telegram_media.ext_for(_m(file=SimpleNamespace(ext=".jpeg")), "photo") == ".jpg"
    assert telegram_media.ext_for(_m(file=None), "video") == ".mp4"
    assert not telegram_media.have(tmp_path, stem)
    (tmp_path / (stem + ".part")).write_bytes(b"x")
    assert not telegram_media.have(tmp_path, stem)
    (tmp_path / (stem + ".jpg")).write_bytes(b"x")
    assert telegram_media.have(tmp_path, stem)
