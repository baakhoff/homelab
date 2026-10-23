"""Tests for pipelines/tools/google_takeout_pack.py, on a made-up Takeout
export, zipped the way Google delivers it. Run from the repo root:

    uv run --with pytest pytest pipelines/tests
"""

import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from google_takeout_pack import mbox_messages, pack, rid  # noqa: E402

MBOX = b"""\
From 1780000000000000001@xxx Mon Oct 19 10:00:00 +0000 2026
X-GM-THRID: 1780000000000000001
X-Gmail-Labels: Inbox,Opened,"Travel, 2026"
From: Ana <Ana@Example.org>
To: me@example.net
Subject: Tickets
Message-ID: <m1@example.org>
Date: Mon, 19 Oct 2026 10:00:00 +0000
Content-Type: text/plain; charset=utf-8

Here they are.
>From the airline, attached.

From 1780000000000000002@xxx Mon Oct 19 11:00:00 +0000 2026
X-GM-THRID: 1780000000000000001
X-Gmail-Labels: Sent
From: Me <me@example.net>
To: Ana <ana@example.org>, bob@example.com
Subject: Re: Tickets
Message-ID: <m2@example.net>
In-Reply-To: <m1@example.org>
Date: Mon, 19 Oct 2026 11:00:00 +0000
Content-Type: text/plain; charset=utf-8

Thanks!
"""

SEARCH = [{"header": "Search", "title": "Searched for trains", "time": "2026-10-19T09:00:00.000Z",
           "products": ["Search"]},
          {"header": "Gmail", "title": "Used Gmail", "time": "2026-10-19T09:30:00.000Z", "products": ["Gmail"]}]
SESSION = {"fitnessActivity": "walking", "startTime": "2026-10-19T05:00:00Z", "endTime": "2026-10-19T05:30:00Z",
           "duration": "1800s", "aggregate": [{"metricName": "com.google.step_count.delta", "intValue": 3000}],
           "segment": [{"fitnessActivity": "walking", "startTime": "2026-10-19T05:00:00Z"}]}
NOTE = {"title": "Shopping", "isPinned": True, "listContent": [{"text": "milk", "isChecked": False}],
        "createdTimestampUsec": 1760850000000000}
CHAT = {"messages": [{"message_id": "abc/1", "text": "hi", "creator": {"name": "Ana", "email": "ana@example.org"},
                      "created_date": "Monday, October 19, 2026 at 10:00:00 AM UTC"}]}
CHROME = {"Browser History": [{"title": "Trains", "url": "https://example.com/", "time_usec": 1760864400000000}]}


def _takeout(tmp_path):
    with zipfile.ZipFile(tmp_path / "takeout-001.zip", "w") as z:
        z.writestr("Takeout/Mail/All mail Including Spam and Trash.mbox", MBOX)
        z.writestr("Takeout/My Activity/Search/MyActivity.json", json.dumps(SEARCH))
        z.writestr("Takeout/My Activity/Search/MyActivity.html", "<html></html>")
        z.writestr("Takeout/Chrome/History.json", json.dumps(CHROME))
        z.writestr("Takeout/Drive/notes.json", json.dumps({"not": "activity"}))
        z.writestr("Takeout/Fit/Daily activity metrics/2026-10-19.csv",
                   "Start time,End time,Step count\n00:00:00.000+02:00,00:15:00.000+02:00,120\n"
                   "00:15:00.000+02:00,00:30:00.000+02:00,80\n")
        z.writestr("Takeout/Fit/All Sessions/2026-10-19T07_00_00+02_00_WALKING.json", json.dumps(SESSION))
        z.writestr("Takeout/Fit/Activities/2026-10-19T07_00_00+02_00_WALKING.tcx", "<xml/>")
        z.writestr("Takeout/Keep/Shopping.json", json.dumps(NOTE))
        z.writestr("Takeout/Google Chat/Groups/DM abc/messages.json", json.dumps(CHAT))
        z.writestr("Takeout/Saved/Restaurants.csv", "Title,Note,URL,Tags,Comment\nNice place,,https://example.com/p,,\n")
        z.writestr("Takeout/Timeline/Settings.json", json.dumps({"timelineEnabled": False}))
    return tmp_path


def _lines(tmp_path):
    out = io.StringIO()
    counts = pack(_takeout(tmp_path), out)
    return counts, [json.loads(line) for line in out.getvalue().splitlines()]


def test_counts(tmp_path):
    counts, _ = _lines(tmp_path)
    assert counts == {"gmail/takeout": 2, "portability/myactivity.search": 1,
                      "portability/myactivity.other": 1, "portability/chrome.history": 1,
                      "takeout/fit/daily": 2, "takeout/fit/sessions": 1, "takeout/keep/notes": 1,
                      "takeout/chat/messages": 1, "takeout/saved": 1}


def test_takeout_products(tmp_path):
    _, lines = _lines(tmp_path)
    by = {}
    for x in lines:
        by.setdefault(x["endpoint"], []).append(x)
    # A workout and a note are one record each, whole, with where they came from.
    session = by["takeout/fit/sessions"][0]
    assert session["record"]["aggregate"] == SESSION["aggregate"]
    assert session["record"]["_file"].endswith("WALKING.json")
    note = by["takeout/keep/notes"][0]
    assert note["id"] == "takeout/keep/notes:Shopping.json" and note["record"]["title"] == "Shopping"
    # CSV rows keep the file - a Fit day's date is only in its name.
    assert {r["record"]["_file"] for r in by["takeout/fit/daily"]} == {"2026-10-19.csv"}
    assert by["takeout/fit/daily"][0]["record"]["Step count"] == "120"
    # A Chat message keeps Google's id, and the conversation's folder.
    chat = by["takeout/chat/messages"][0]
    assert chat["id"] == "abc/1" and chat["record"]["_dir"] == "DM abc"
    assert by["takeout/saved"][0]["record"]["_file"] == "Restaurants.csv"
    # Packing twice gives the same ids, so a second load adds nothing.
    (tmp_path / "again").mkdir()
    _, again = _lines(tmp_path / "again")
    assert sorted(x["id"] for x in again) == sorted(x["id"] for x in lines)


def test_mail(tmp_path):
    _, lines = _lines(tmp_path)
    mail = {x["id"]: x["record"] for x in lines if x["endpoint"] == "gmail/takeout"}
    first, reply = mail["<m1@example.org>"], mail["<m2@example.net>"]
    assert first["gmail_thread_id"] == format(1780000000000000001, "x")
    assert first["labels"] == ["Inbox", "Opened", "Travel, 2026"]
    assert first["from"] == {"name": "Ana", "address": "ana@example.org"}
    # mboxrd quoting undone, the next message's separator not in the body.
    assert first["body_text"] == "Here they are.\nFrom the airline, attached."
    assert reply["labels"] == ["Sent"]
    assert [p["address"] for p in reply["to"]] == ["ana@example.org", "bob@example.com"]
    assert reply["in_reply_to"] == "<m1@example.org>"
    assert reply["time"].startswith("2026-10-19T11:00:00")


def test_activity_ids_match_the_portability_dag(tmp_path):
    _, lines = _lines(tmp_path)
    search = next(x for x in lines if x["endpoint"] == "portability/myactivity.search")
    assert search["id"] == rid("myactivity.search", None, SEARCH[0])
    chrome = next(x for x in lines if x["endpoint"] == "portability/chrome.history")
    assert chrome["id"] == rid("chrome.history", "Browser History", CHROME["Browser History"][0])
    assert chrome["section"] == "Browser History"


def test_mbox_split():
    assert len(list(mbox_messages(io.BytesIO(MBOX)))) == 2
