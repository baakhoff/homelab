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


def test_kind():
    assert vk_media.kind("", "https://vk.com/video-12_34") == "video"
    assert vk_media.kind("Видеозапись", "https://vk.com/video?z=video1_2") == "video"
    assert vk_media.kind("Фотография", "https://example.com/x") == "photo"
    assert vk_media.kind("Документ", "https://example.com/doc") is None


def test_fetch(tmp_path, monkeypatch):
    videos = []

    def fake_video(url, folder, t):
        videos.append(url)
        (folder / f"{vk_media.stem_for(url, t)}.mp4").write_bytes(b"v")
        return True

    monkeypatch.setattr(vk_media, "get", lambda url: b"x" * 2048 if "wall" in url else None)
    monkeypatch.setattr(vk_media, "get_video", fake_video)
    monkeypatch.setattr(vk_media, "ytdlp", lambda: ["yt-dlp"])
    out = tmp_path / "media"
    vk_media.fetch(_zip(tmp_path), out)
    names = sorted(f.name for f in out.iterdir())
    assert [n[:19] for n in names] == ["VK_00000000_000000_", "VK_20180503_091500_"]
    assert names[0].endswith(".mp4") and names[1].endswith(".jpg")
    photo = out / names[1]
    assert datetime.fromtimestamp(os.path.getmtime(photo)) == datetime(2018, 5, 3, 9, 15)
    vk_media.fetch(_zip(tmp_path), out)  # a second run fetches nothing new
    assert len(list(out.iterdir())) == 2 and videos == ["https://vk.com/video1_2"]


def test_video_command(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        out = cmd[cmd.index("-o") + 1].replace("%(ext)s", "mp4")
        Path(out).write_bytes(b"v")
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(vk_media, "ytdlp", lambda: ["yt-dlp"])
    monkeypatch.setattr(vk_media.subprocess, "run", fake_run)
    assert vk_media.get_video("https://vk.com/video1_2", tmp_path, "2019-01-12T10:05:07")
    cmd = seen["cmd"]
    assert cmd[cmd.index("--max-filesize") + 1] == "1G"
    assert "filesize<1G" in cmd[cmd.index("-f") + 1]
    (f,) = tmp_path.iterdir()
    assert datetime.fromtimestamp(os.path.getmtime(f)) == datetime(2019, 1, 12, 10, 5, 7)
