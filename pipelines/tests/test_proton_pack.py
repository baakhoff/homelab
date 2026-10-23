"""Tests for pipelines/tools/proton_pack.py, on a made-up export in the
layout Proton's Mail Export tool writes. Run from the repo root:

    uv run --with pytest pytest pipelines/tests
"""

import gzip
import io
import json
import sys
from pathlib import Path

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


def _export(tmp_path):
    mail = tmp_path / "Me@example.net" / "mail_20261023_121456"
    mail.mkdir(parents=True)
    (mail / "abc.eml").write_bytes(EML)
    (mail / "abc.metadata.json").write_text(json.dumps(META))
    (mail / "labels.json").write_text(json.dumps([{"ID": "lbl1", "Name": "Travel", "Path": "Travel"}]))
    return tmp_path


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
