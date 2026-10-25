"""Tests for pipelines/tools/proton_pack.py, on a made-up export in the
layout Proton's Mail Export tool writes. Run from the repo root:

    uv run --with pytest pytest pipelines/tests
"""

import gzip
import io
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from proton_pack import html_to_text, pack  # noqa: E402

EML = b"""\
From: Ana <ana@example.org>
To: Me <me@example.net>, Bob <BOB@example.com>
Cc: carol@example.com
Subject: Re: Plans
Message-ID: <three@example.org>
In-Reply-To: <two@example.net>
References: <one@example.org> <two@example.net>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="b1"

--b1
Content-Type: multipart/alternative; boundary="b2"

--b2
Content-Type: text/html; charset=utf-8

<html><head><style>p{}</style></head><body><p>Hello&nbsp;there,</p><p>see you <b>Friday</b>.</p></body></html>
--b2--
--b1
Content-Type: application/pdf; name="ticket.pdf"
Content-Disposition: attachment; filename="ticket.pdf"
Content-Transfer-Encoding: base64

JVBERi0xLjQK
--b1--
"""

META = {
    "Version": 1,
    "Payload": {
        "ID": "abc==",
        "ExternalID": "three@example.org",
        "Subject": "Re: Plans",
        "Sender": {"Name": "Ana", "Address": "Ana@Example.org"},
        "ToList": [{"Name": "Me", "Address": "me@example.net"}],
        "ReplyTos": [{"Name": "Ana", "Address": "ana@example.org"}],
        "LabelIDs": ["0", "5", "lbl1"],
        "Time": 1760000000,
        "Size": 1234,
        "Unread": 0,
        "IsReplied": 1,
        "IsRepliedAll": 0,
        "IsForwarded": 0,
        "Flags": 1,
    },
}


# A second message: an empty attachment first, then an inline image.
EML_IMAGE = b"""\
From: Me <me@example.net>
To: Ana <ana@example.org>
Subject: Logo
Message-ID: <four@example.net>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="b1"

--b1
Content-Type: text/plain; charset=utf-8

Our logo.
--b1
Content-Type: text/plain; name="empty.txt"
Content-Disposition: attachment; filename="empty.txt"

--b1
Content-Type: image/png; name="logo.png"
Content-Disposition: inline; filename="logo.png"
Content-Transfer-Encoding: base64

iVBORw0K
--b1--
"""


def _export(tmp_path):
    mail = tmp_path / "Me@example.net" / "mail_20261023_121456"
    mail.mkdir(parents=True)
    (mail / "abc.eml").write_bytes(EML)
    (mail / "abc.metadata.json").write_text(json.dumps(META))
    (mail / "labels.json").write_text(json.dumps([{"ID": "lbl1", "Name": "Travel", "Path": "Travel"}]))
    return tmp_path


def _manifest(files):
    return [json.loads(line) for line in (files / "files.jsonl").read_text().splitlines()]


def test_pack(tmp_path):
    out = io.StringIO()
    counts = pack(_export(tmp_path), out)
    assert counts == {"messages": 1, "failed": 0, "truncated": 0, "attachments": 1}
    line = json.loads(out.getvalue())
    assert line["endpoint"] == "messages" and line["id"] == "abc=="
    r = line["record"]
    assert r["account"] == "me@example.net"
    assert r["from"] == {"name": "Ana", "address": "ana@example.org"}
    assert [p["address"] for p in r["to"]] == ["me@example.net", "bob@example.com"]
    assert [p["address"] for p in r["cc"]] == ["carol@example.com"]
    assert r["bcc"] == []
    assert r["thread_id"] == "<one@example.org>"
    assert r["in_reply_to"] == "<two@example.net>"
    assert r["message_id"] == "<three@example.org>"
    assert r["labels"] == ["Inbox", "All Mail", "Travel"]
    assert r["time"].startswith("2025-10-09T")
    # The HTML part, tags and styles gone, paragraphs kept.
    assert r["body_text"] == "Hello there,\n\nsee you Friday."
    assert r["attachments"] == [{"name": "ticket.pdf", "mime_type": "application/pdf",
                                 "size": 9, "inline": False}]
    assert r["replied"] is True and r["unread"] is False


def test_files(tmp_path):
    export = _export(tmp_path / "e")
    mail = next(export.glob("*/mail_*"))
    (mail / "def.eml").write_bytes(EML_IMAGE)
    (mail / "def.metadata.json").write_text(json.dumps({"Payload": {**META["Payload"], "ID": "d/e+f=="}}))
    files = tmp_path / "files"
    files.mkdir()
    out = io.StringIO()
    counts = pack(export, out, files)
    assert counts["messages"] == 2 and counts["attachments"] == 3 and counts["files"] == 2
    # A folder per message by its number, never its Proton id, and each
    # file by its position; the empty one is left out, its number kept.
    assert sorted(p.relative_to(files).as_posix() for p in files.rglob("*") if p.is_file()) == [
        "1/1", "2/2", "files.jsonl"]
    assert (files / "1" / "1").read_bytes() == b"%PDF-1.4\n"
    assert (files / "2" / "2").read_bytes() == b"\x89PNG\r\n"
    assert _manifest(files) == [
        {"file": "1/1", "endpoint": "proton", "id": "abc==/1",
         "record": {"name": "ticket.pdf", "mime_type": "application/pdf", "inline": False}},
        {"file": "2/2", "endpoint": "proton", "id": "d/e+f==/2",
         "record": {"name": "logo.png", "mime_type": "image/png", "inline": True}},
    ]
    # The packed file still lists the empty one.
    second = json.loads(out.getvalue().splitlines()[1])["record"]
    assert [a["size"] for a in second["attachments"]] == [0, 6]


def test_files_into_the_archive(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))
    import archive

    for d in ("inbox", "objects", "tmp"):
        (tmp_path / d).mkdir()
    monkeypatch.setattr(archive, "ROOT", tmp_path)
    batch = tmp_path / "inbox" / "proton-2026-10"
    batch.mkdir()
    pack(_export(tmp_path / "e"), io.StringIO(), batch)
    sent = []

    class Files:
        def send(self, endpoint, rid, record):
            sent.append((endpoint, rid, record))

        def flush(self):
            pass

    archive._take(batch, tmp_path / "inbox", Files(), time.monotonic())
    [(endpoint, rid, record)] = sent
    assert (endpoint, rid) == ("proton", "abc==/1")
    assert record["name"] == "ticket.pdf" and record["mime_type"] == "application/pdf"
    assert (tmp_path / record["object"]).read_bytes() == b"%PDF-1.4\n"


def test_bad_message_is_skipped(tmp_path):
    export = _export(tmp_path)
    mail = next(export.glob("*/mail_*"))
    (mail / "bad.metadata.json").write_text("{not json")
    (mail / "bad.eml").write_bytes(b"")
    counts = pack(export, io.StringIO())
    assert counts["messages"] == 1 and counts["failed"] == 1


def test_html_to_text():
    assert html_to_text("<div>a</div><script>x()</script><div>b<br>c</div>") == "a\n\nb\nc"


def test_main_writes_gzip(tmp_path, monkeypatch):
    import proton_pack

    target = tmp_path / "out.jsonl.gz"
    monkeypatch.setattr(sys, "argv", ["proton_pack.py", str(_export(tmp_path / "e")), str(target)])
    proton_pack.main()
    with gzip.open(target, "rt", encoding="utf-8") as f:
        assert len(f.readlines()) == 1


def test_main_files(tmp_path, monkeypatch):
    import proton_pack

    files = tmp_path / "files"
    argv = ["proton_pack.py", str(_export(tmp_path / "e")), str(tmp_path / "out.jsonl.gz"), "--files", str(files)]
    monkeypatch.setattr(sys, "argv", argv)
    proton_pack.main()
    assert (files / "1" / "1").exists() and len(_manifest(files)) == 1
    # A second pack into the same folder would mix the two.
    with pytest.raises(SystemExit, match="not empty"):
        proton_pack.main()
