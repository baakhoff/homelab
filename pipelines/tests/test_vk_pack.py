"""Tests for pipelines/tools/vk_pack.py, on a made-up VK archive in the
layout and encoding VK's data export used. Run from the repo root:

    uv run --with pytest pytest pipelines/tests
"""

import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from vk_pack import pack, when  # noqa: E402

HEAD = '<html><head><meta http-equiv="Content-Type" content="text/html; charset=windows-1251"></head><body>'
CRUMBS = ('<div class="ui_crumb">Сообщения</div><div class="ui_crumb_sep">»</div>'
          '<div class="ui_crumb">Анна Петрова</div>')

INDEX = HEAD + ('<div class="item"><div class="message-peer--id"><a href="1001/messages0.html">Анна Петрова</a>'
                '</div></div><div class="item"><div class="message-peer--id">'
                '<a href="2000000001/messages0.html">Друзья</a></div></div></body></html>')

MESSAGES = HEAD + CRUMBS + '''
<div class="item"><div class="item__main"><div class="message" data-id="555">
  <div class="message__header"><a href="https://vk.com/id1001">Анна Петрова</a>, 12 янв 2019 в 10:05:07</div>
  <div>Привет! Как дела?<div class="kludges"><div class="attachment">
    <div class="attachment__description">Фотография</div>
    <a class="attachment__link" href="https://example.com/p.jpg">https://example.com/p.jpg</a>
  </div></div></div>
</div></div></div>
<div class="item"><div class="item__main"><div class="message" data-id="556">
  <div class="message__header">Вы, 12 янв 2019 в 10:06:00 (ред.)</div>
  <div>Хорошо<br>спасибо</div>
</div></div></div>
</body></html>'''

AUDIO = HEAD + ('<div class="ui_crumb">Музыка</div><div class="item"><div class="clear_fix audio">'
                '<div class="fl_l audio__title">Кино — Группа крови</div>'
                '<div class="fl_r audio__duration">4:45</div></div></div></body></html>')

WALL = HEAD + ('<div class="item"><div class="post__link fl_l"><a href="https://vk.com/wall1_1">Запись</a></div>'
               '<div>С днём рождения! 3 мая 2018 в 9:15</div></div></body></html>')


def _archive(tmp_path):
    path = tmp_path / "VK Data.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("VK Data/index.html", (HEAD + "</body></html>").encode("cp1251"))
        z.writestr("VK Data/messages/index-messages.html", INDEX.encode("cp1251"))
        z.writestr("VK Data/messages/1001/messages0.html", MESSAGES.encode("cp1251"))
        z.writestr("VK Data/audio/0/audio0.html", AUDIO.encode("cp1251"))
        z.writestr("VK Data/wall/0/wall0.html", WALL.encode("cp1251"))
        z.writestr("VK Data/style.css", "body{}")
    return path


def _lines(tmp_path):
    out = io.StringIO()
    counts = pack(_archive(tmp_path), out)
    return counts, [json.loads(x) for x in out.getvalue().splitlines()]


def test_counts(tmp_path):
    counts, _ = _lines(tmp_path)
    assert counts == {"vk/conversations": 2, "vk/messages": 2, "vk/audio": 1, "vk/items": 1}


def test_messages(tmp_path):
    _, lines = _lines(tmp_path)
    msgs = {x["id"]: x["record"] for x in lines if x["endpoint"] == "vk/messages"}
    first, reply = msgs["1001/555"], msgs["1001/556"]
    assert first["conversation_name"] == "Анна Петрова"
    assert first["sender_name"] == "Анна Петрова" and first["sender_link"] == "https://vk.com/id1001"
    assert first["outgoing"] is False and first["time"] == "2019-01-12T10:05:07"
    assert first["text"] == "Привет! Как дела?"
    assert first["attachments"] == [{"description": "Фотография", "links": ["https://example.com/p.jpg"]}]
    assert reply["outgoing"] is True and reply["sender_name"] == ""
    assert reply["edited"] is True and reply["time"] == "2019-01-12T10:06:00"
    assert reply["text"] == "Хорошо\nспасибо"


def test_conversations_audio_items(tmp_path):
    _, lines = _lines(tmp_path)
    convs = {x["id"]: x["record"]["name"] for x in lines if x["endpoint"] == "vk/conversations"}
    assert convs == {"1001": "Анна Петрова", "2000000001": "Друзья"}
    audio = next(x["record"] for x in lines if x["endpoint"] == "vk/audio")
    assert audio["title"] == "Кино — Группа крови" and audio["duration"] == "4:45"
    wall = next(x["record"] for x in lines if x["endpoint"] == "vk/items")
    assert wall["section"] == "wall" and wall["time"] == "2018-05-03T09:15:00"
    assert wall["links"] == ["https://vk.com/wall1_1"]


def test_when():
    assert when("5 мар 2019 в 13:44:18") == "2019-03-05T13:44:18"
    assert when("1 мая 2017 в 0:01") == "2017-05-01T00:01:00"
    assert when("no date here") is None
