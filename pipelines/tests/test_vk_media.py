"""Tests for pipelines/tools/vk_media.py, on the made-up VK archive of
test_vk_pack.py. No network: fetching is given a stand-in. Run from the
repo root:

    uv run --with pytest pytest pipelines/tests
"""

import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import vk_media  # noqa: E402
from test_vk_pack import HEAD, _archive  # noqa: E402

PHOTOS = HEAD + ('<div class="item"><div>Фото со стены, 3 мая 2018 в 9:15</div>'
                 '<a href="https://example.com/wall.jpg?size=x">фото</a></div>'
                 '<div class="item"><div class="attachment"><div class="attachment__description">Видеозапись</div>'
                 '<a class="attachment__link" href="https://vk.com/video1_2">видео</a></div></div></body></html>')


def _zip(tmp_path):
    path = _archive(tmp_path)
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("VK Data/photos/0/photos0.html", PHOTOS.encode("cp1251"))
    return path


def test_collect(tmp_path):
    found = vk_media.collect(_zip(tmp_path))
    assert found == {
        "https://example.com/p.jpg": {"kind": "photo", "time": "2019-01-12T10:05:07"},
        "https://example.com/wall.jpg?size=x": {"kind": "photo", "time": "2018-05-03T09:15:00"},
        "https://vk.com/video1_2": {"kind": "video", "time": None},
    }


def test_name():
    assert vk_media.name_for("https://example.com/p.jpeg", "2019-01-12T10:05:07").startswith("VK_20190112_100507_")
    assert vk_media.name_for("https://example.com/p.jpeg", None).endswith(".jpg")


def test_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(vk_media, "get", lambda url: b"x" * 2048 if "wall" in url else None)
    out = tmp_path / "media"
    vk_media.fetch(_zip(tmp_path), out)
    files = list(out.iterdir())
    assert [f.name[:19] for f in files] == ["VK_20180503_091500_"]
    assert datetime.fromtimestamp(os.path.getmtime(files[0])) == datetime(2018, 5, 3, 9, 15)
    vk_media.fetch(_zip(tmp_path), out)  # a second run fetches nothing new
    assert len(list(out.iterdir())) == 1
