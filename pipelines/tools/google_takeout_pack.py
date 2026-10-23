#!/usr/bin/env python3
"""Pack a Google Takeout export into one file for the ingest_google_takeout DAG.

    python3 pipelines/tools/google_takeout_pack.py ~/Downloads/takeout ~/google-takeout.jsonl.gz

The input is the folder Takeout's zips were unpacked into, or the folder
holding the zips themselves - either works. Two kinds of data are read,
the rest is ignored:

- Gmail's mbox: every message with its headers, its body as plain text and
  its attachments' names and sizes, never the files - the bodies the hourly
  Gmail DAG's token cannot read. Endpoint gmail/takeout, keyed by the
  Message-ID header; the Gmail thread id is kept in the hex the API uses,
  so a body joins its message in google_gmail_messages.
- My Activity and Chrome history, exported as JSON (Takeout's default for
  My Activity is HTML: choose JSON). Sent under the same endpoints and with
  the same ids as the Data Portability exports (pipelines/dags/google.py),
  so the two ways in feed the same models and an item that came both ways
  is one row.

Nothing is masked here; the DAG does that. The output is as private as the
export: keep it beside it, and delete both once the load is done. Standard
library only, plus proton_pack.py beside this file for the mail parsing.
Prints counts, never contents. The procedure: pipelines/google.md.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sys
import zipfile
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proton_pack import BODY_MAX, _msgids, _people, attachments, body_text  # noqa: E402

# My Activity's `products` -> the Data Portability resource of the same
# data. Anything else is still kept, as myactivity.other.
PRODUCTS = {
    "Search": "myactivity.search", "Image Search": "myactivity.search", "Video Search": "myactivity.search",
    "YouTube": "myactivity.youtube", "Maps": "myactivity.maps", "Google Play Store": "myactivity.play",
    "Shopping": "myactivity.shopping", "Ads": "myactivity.myadcenter",
}


def rid(resource: str, section, item) -> str:
    """The id the Portability DAG gives the same item - see its load()."""
    digest = json.dumps([resource, section, item], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(digest.encode()).hexdigest()[:32]


def mbox_messages(fh):
    """Raw messages out of an mbox stream, one at a time, without reading
    the whole file - Takeout's can be gigabytes."""
    lines: list[bytes] = []
    for line in fh:
        if line.startswith(b"From ") and (not lines or lines[-1] in (b"\n", b"\r\n")):
            if lines:
                yield b"".join(lines)
            lines = []
            continue
        if line.startswith(b">") and line.lstrip(b">").startswith(b"From "):
            line = line[1:]
        lines.append(line)
    if lines:
        yield b"".join(lines)


def gmail_record(raw: bytes) -> dict:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    message_id = (_msgids(msg["Message-ID"]) or [""])[0]
    try:
        sent = parsedate_to_datetime(str(msg["Date"])).isoformat() if msg["Date"] else None
    except (TypeError, ValueError):
        sent = None
    thrid = str(msg["X-GM-THRID"] or "").strip()
    body = body_text(msg)
    sender = _people(msg["From"] or "")
    return {
        "message_id": message_id,
        "gmail_thread_id": format(int(thrid), "x") if thrid.isdigit() else "",
        "in_reply_to": (_msgids(msg["In-Reply-To"]) or [""])[0],
        "references": _msgids(msg["References"]),
        "time": sent,
        "subject": str(msg["Subject"] or ""),
        "from": sender[0] if sender else {"name": "", "address": ""},
        "to": _people(msg["To"] or ""),
        "cc": _people(msg["Cc"] or ""),
        "bcc": _people(msg["Bcc"] or ""),
        # Comma-separated, a label with a comma in it quoted.
        "labels": [x.strip() for x in next(csv.reader([str(msg["X-Gmail-Labels"] or "")]), []) if x.strip()],
        "list_id": str(msg["List-Id"] or ""),
        "body_text": body[:BODY_MAX],
        "body_truncated": len(body) > BODY_MAX,
        "attachments": attachments(msg),
    }


def json_items(name: str, data):
    """(endpoint, id, record, section) for My Activity and Chrome history."""
    if isinstance(data, dict) and isinstance(data.get("Browser History"), list):
        for item in data["Browser History"]:
            yield "portability/chrome.history", rid("chrome.history", "Browser History", item), item, "Browser History"
    elif isinstance(data, list) and data and isinstance(data[0], dict) and "header" in data[0] and "time" in data[0]:
        for item in data:
            products = item.get("products") or [item.get("header", "")]
            resource = PRODUCTS.get(products[0], "myactivity.other")
            yield f"portability/{resource}", rid(resource, None, item), item, None


def files(root: Path):
    """(name, opener) for every file under root, inside zips too."""
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if not info.is_dir():
                        yield info.filename, lambda z=z, info=info: z.open(info)
        else:
            yield str(path.relative_to(root)), lambda path=path: open(path, "rb")


def pack(root: Path, out) -> dict:
    counts: dict[str, int] = {}

    def write(endpoint, rid_, record, **extra):
        out.write(json.dumps({"endpoint": endpoint, "id": rid_, "record": record, **extra},
                             ensure_ascii=False) + "\n")
        counts[endpoint] = counts.get(endpoint, 0) + 1

    for name, opener in files(root):
        lower = name.lower()
        if lower.endswith(".mbox"):
            with opener() as fh:
                for raw in mbox_messages(fh):
                    try:
                        rec = gmail_record(raw)
                    except Exception as e:  # one bad message never stops the rest
                        counts["failed"] = counts.get("failed", 0) + 1
                        print(f"skipped a message in {Path(name).name}: {type(e).__name__}", file=sys.stderr)
                        continue
                    key = rec["message_id"] or "sha:" + hashlib.sha256(raw[:65536]).hexdigest()[:32]
                    write("gmail/takeout", key, rec, file=Path(name).name)
        elif lower.endswith(".json"):
            with opener() as fh:
                try:
                    data = json.load(fh)
                except ValueError:
                    continue
            for endpoint, rid_, item, section in json_items(name, data):
                write(endpoint, rid_, item, file=Path(name).name, section=section)
    return counts


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: google_takeout_pack.py <takeout folder> <output .jsonl.gz>")
    root, target = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    with gzip.open(target, "wt", encoding="utf-8") as out:
        counts = pack(root, out)
    print(f"{target}: {counts}, {target.stat().st_size / 1e6:.1f} MB")
    if not any(k != "failed" for k in counts):
        sys.exit("nothing found - Gmail as mbox, My Activity as JSON or Chrome history in that folder?")


if __name__ == "__main__":
    main()
