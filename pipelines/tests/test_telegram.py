"""Tests for pipelines/dags/telegram.py's choice of which media go into the
archive. Run from the repo root:

    uv run --with pytest pytest pipelines/tests

telegram.py is a DAG file: Airflow and pendulum are not installed here, and
nothing tested reaches them, so stand-ins take their place for the import.
Telethon is imported only inside the functions that talk to Telegram.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

for name in ("airflow", "airflow.sdk", "pendulum"):
    sys.modules.setdefault(name, MagicMock())
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))
import telegram  # noqa: E402


def test_files_are_archived():
    for kind in ("photo", "video", "voice", "video_note", "audio", "document"):
        assert telegram.to_archive({"kind": kind, "size": 1000})


def test_the_rest_stays_metadata():
    assert not telegram.to_archive(None)
    for kind in ("sticker", "gif", "geo", "contact", "poll", "dice", "webpage"):
        assert not telegram.to_archive({"kind": kind, "size": 1000})


def test_link_preview_is_not_a_photo():
    # _media() calls a preview's picture a photo; its url gives it away.
    assert not telegram.to_archive({"kind": "photo", "size": 1000, "url": "https://example.com"})


def test_no_file_left():
    # A self-destructing photo once seen: the kind is there, the file is not.
    assert not telegram.to_archive({"kind": "photo"})
