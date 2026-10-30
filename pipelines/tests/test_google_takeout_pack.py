"""Tests for pipelines/tools/google_takeout_pack.py, on a made-up Takeout
export, zipped the way Google delivers it. Run from the repo root:

    uv run --with pytest pytest pipelines/tests
"""

import gzip
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from google_takeout_pack import mbox_messages, pack, rid  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

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
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="b1"

--b1
Content-Type: text/plain; charset=utf-8

Thanks!
--b1
Content-Type: application/pdf; name="seats.pdf"
Content-Disposition: attachment; filename="seats.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQK
--b1--
"""

SEARCH = [{"header": "Search", "title": "Searched for trains", "time": "2026-10-19T09:00:00.000Z",
           "products": ["Search"]},
          {"header": "Gmail", "title": "Used Gmail", "time": "2026-10-19T09:30:00.000Z", "products": ["Gmail"]}]
SESSION = {"fitnessActivity": "walking", "startTime": "2026-10-19T05:00:00Z", "endTime": "2026-10-19T05:30:00Z",
           "duration": "1800s", "aggregate": [{"metricName": "com.google.step_count.delta", "intValue": 3000}],
           "segment": [{"fitnessActivity": "walking", "startTime": "2026-10-19T05:00:00Z"}]}
NOTE = {"title": "Shopping", "isPinned": True, "listContent": [{"text": "milk", "isChecked": False}],
        "createdTimestampUsec": 1760850000000000,
        # The image is listed as .jpg and exported as .jpeg, in the export's other part.
        "attachments": [{"filePath": "1a2b.jpg", "mimetype": "image/jpeg"},
                        {"filePath": "3c4d.3gp", "mimetype": "audio/3gpp"}]}
CHAT = {"messages": [{"message_id": "abc/1", "text": "hi", "creator": {"name": "Ana", "email": "ana@example.org"},
                      "created_date": "Monday, October 19, 2026 at 10:00:00 AM UTC"}]}
CHROME = {"Browser History": [{"title": "Trains", "url": "https://example.com/", "time_usec": 1760864400000000}]}


def _takeout(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    with zipfile.ZipFile(tmp_path / "takeout-001.zip", "w") as z:
        z.writestr("Takeout/Mail/All mail Including Spam and Trash.mbox", MBOX)
        z.writestr("Takeout/My Activity/Search/MyActivity.json", json.dumps(SEARCH))
        z.writestr("Takeout/My Activity/Search/MyActivity.html", "<html></html>")
        z.writestr("Takeout/Chrome/History.json", json.dumps(CHROME))
        z.writestr("Takeout/Drive/notes.json", json.dumps({"not": "activity"}))
        z.writestr("Takeout/Drive/Reports/Q3.docx", b"PK docx")
        z.writestr("Takeout/Drive/old.mbox", MBOX)
        z.writestr("Takeout/Drive/empty.txt", b"")
        z.writestr("Takeout/Fit/Daily activity metrics/2026-10-19.csv",
                   "Start time,End time,Step count\n00:00:00.000+02:00,00:15:00.000+02:00,120\n"
                   "00:15:00.000+02:00,00:30:00.000+02:00,80\n")
        z.writestr("Takeout/Fit/All Sessions/2026-10-19T07_00_00+02_00_WALKING.json", json.dumps(SESSION))
        z.writestr("Takeout/Fit/Activities/2026-10-19T07_00_00+02_00_WALKING.tcx", "<xml/>")
        z.writestr("Takeout/Fit/Activities/2026-10-20T07_00_00+02_00_RUNNING.tcx", "<run/>")
        z.writestr("Takeout/Keep/Shopping.json", json.dumps(NOTE))
        z.writestr("Takeout/Keep/3c4d.3gp", b"audio")
        z.writestr("Takeout/Google Chat/Groups/DM abc/messages.json", json.dumps(CHAT))
        z.writestr("Takeout/Saved/Restaurants.csv", "Title,Note,URL,Tags,Comment\nNice place,,https://example.com/p,,\n")
        z.writestr("Takeout/Timeline/Settings.json", json.dumps({"timelineEnabled": False}))
    with zipfile.ZipFile(tmp_path / "takeout-002.zip", "w") as z:
        z.writestr("Takeout/Keep/1a2b.jpeg", b"image")
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


def _files(root, files):
    counts = pack(root, io.StringIO(), files)
    manifest = [json.loads(line) for line in (files / "files.jsonl").read_text().splitlines()]
    return counts, {(m["endpoint"], m["id"]): m for m in manifest}


def test_files(tmp_path):
    counts, by = _files(_takeout(tmp_path / "export"), tmp_path / "files")
    assert {k: v for k, v in counts.items() if k.startswith("files/")} == {
        "files/gmail": 1, "files/keep": 2, "files/fit": 2, "files/drive": 3}
    # A mail's attachment, by its message's key and its place in the list.
    mail = by["google/gmail", "<m2@example.net>/1"]
    assert mail["file"] == "gmail/2/1"
    assert mail["record"] == {"name": "seats.pdf", "mime_type": "application/pdf", "inline": False}
    assert (tmp_path / "files" / mail["file"]).read_bytes() == b"%PDF-1.4\n"
    # A Keep note's files by the note's key, the one listed as .jpg found
    # as the .jpeg it was exported as, in the other zip.
    image = by["google/keep", "takeout/keep/notes:Shopping.json/1"]
    assert image["record"] == {"name": "1a2b.jpeg", "mime_type": "image/jpeg"}
    assert (tmp_path / "files" / image["file"]).read_bytes() == b"image"
    assert by["google/keep", "takeout/keep/notes:Shopping.json/2"]["record"]["mime_type"] == "audio/3gpp"
    # A track with a session of its name is keyed as the session is; one
    # without, by its path.
    assert ("google/fit", "takeout/fit/sessions:2026-10-19T07_00_00+02_00_WALKING.json") in by
    assert ("google/fit", "Activities/2026-10-20T07_00_00+02_00_RUNNING.tcx") in by
    # Drive's files as they are, by their path under Drive - an mbox there
    # too, never read as mail (test_counts) - and the empty one left out.
    doc = by["google/drive", "Reports/Q3.docx"]
    assert doc["record"] == {"name": "Q3.docx", "mime_type": DOCX}
    assert (tmp_path / "files" / doc["file"]).read_bytes() == b"PK docx"
    assert ("google/drive", "old.mbox") in by and ("google/drive", "empty.txt") not in by
    # Every file is under a number, never its name in the export.
    assert {m["file"].split("/")[0] for m in by.values()} == {"gmail", "keep", "fit", "drive"}
    assert all(part.isdigit() for m in by.values() for part in m["file"].split("/")[1:])


def test_files_from_an_unpacked_folder(tmp_path):
    export = _takeout(tmp_path / "export")
    unpacked = tmp_path / "unpacked"
    for part in sorted(export.glob("*.zip")):
        with zipfile.ZipFile(part) as z:
            z.extractall(unpacked)
    zipped = _files(export, tmp_path / "a")
    loose = _files(unpacked, tmp_path / "b")
    assert loose[0] == zipped[0]
    assert {k: m["record"] for k, m in loose[1].items()} == {k: m["record"] for k, m in zipped[1].items()}
    image = loose[1]["google/keep", "takeout/keep/notes:Shopping.json/1"]
    assert (tmp_path / "b" / image["file"]).read_bytes() == b"image"


def test_main_files(tmp_path, monkeypatch):
    import google_takeout_pack

    files = tmp_path / "files"
    target = tmp_path / "out.jsonl.gz"
    argv = ["google_takeout_pack.py", str(_takeout(tmp_path / "export")), str(target), "--files", str(files)]
    monkeypatch.setattr(sys, "argv", argv)
    google_takeout_pack.main()
    with gzip.open(target, "rt", encoding="utf-8") as f:
        assert len(f.readlines()) == 11
    assert len((files / "files.jsonl").read_text().splitlines()) == 8
