#!/usr/bin/env python3
"""Pack a Google Takeout export into one file for the ingest_google_takeout DAG.

    python3 pipelines/tools/google_takeout_pack.py ~/Downloads/takeout ~/google-takeout.jsonl.gz \
        --files ~/google-takeout-files

The input is the folder Takeout's zips were unpacked into, or the folder
holding the zips themselves - either works. Three kinds of data are read,
the rest is ignored:

- Gmail's mbox: every message with its headers, its body as plain text and
  its attachments' names and sizes - the bodies the hourly Gmail DAG's
  token cannot read. Endpoint gmail/takeout, keyed by the Message-ID
  header; the Gmail thread id is kept in the hex the API uses, so a body
  joins its message in google_gmail_messages.
- My Activity and Chrome history, exported as JSON (Takeout's default for
  My Activity is HTML: choose JSON). Sent under the same endpoints and with
  the same ids as the Data Portability exports (pipelines/dags/google.py),
  so the two ways in feed the same models and an item that came both ways
  is one row.
- The products in TAKEOUT below - Fit, Keep, Chat, Pay, Maps and the rest
  worth having - each CSV row or JSON item as it is, under endpoint
  takeout/<name>; one file is one record where the file is one thing (a
  note, a workout). Photos, HTML and the rest are skipped.

With --files, the export's files go to the NAS archive too: each one into
that folder under a number, never its own name - a path in the export may
not suit the share - with a line in the folder's files.jsonl, the manifest
the archive's inbox keys it by (pipelines/files.md). Empty ones are left
out. Four kinds:

- gmail/<n>/<position>: a mail's attachments, decoded, n a running number
  for the message. Endpoint google/gmail, id <Message-ID>/<position>, the
  position from 1 in the order google_gmail_bodies lists them.
- keep/<n>: the images and recordings a Keep note lists. google/keep,
  <the note's key in google_keep_notes>/<position in its list>. One the
  export does not hold is counted as files/missing.
- fit/<n>: Fit's activity files, the tracks under Activities/. google/fit,
  keyed as the session of the same name in All Sessions is in
  google_fit_sessions, or by the path under Fit when there is none.
- drive/<n>: everything under Drive, as it is - Docs and Sheets come
  converted, as .docx, .xlsx and the like. google/drive, the path under
  Drive. Files there are never read as data: an mbox kept in Drive is not
  the account's mail.

Nothing is masked here; the DAG does that. The output is as private as the
export: keep it beside it, and delete both once the load is done; the files
folder too, once it is in the inbox. Standard library only, plus
proton_pack.py beside this file for the mail parsing. Prints counts, never
contents. The procedure: pipelines/google.md.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import io
import hashlib
import json
import mimetypes
import posixpath
import sys
import zipfile
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proton_pack import (  # noqa: E402
    BODY_MAX, _msgids, _people, attachments, body_text, empty_folder, folder_size, save_attachments, save_file,
)

# My Activity's `products` -> the Data Portability resource of the same
# data. Anything else is still kept, as myactivity.other.
PRODUCTS = {
    "Search": "myactivity.search", "Image Search": "myactivity.search", "Video Search": "myactivity.search",
    "YouTube": "myactivity.youtube", "Maps": "myactivity.maps", "Google Play Store": "myactivity.play",
    "Shopping": "myactivity.shopping", "Ads": "myactivity.myadcenter",
}


# Takeout product, sub-folder ("" for files at the product's top) -> the
# endpoint its CSV rows and JSON items go to, and whether a JSON file is one
# record (a note, a workout) rather than a list of them. Products and
# folders not here are not read.
TAKEOUT = {
    ("Fit", "Daily activity metrics"): ("takeout/fit/daily", False),
    ("Fit", "All Sessions"): ("takeout/fit/sessions", True),
    ("Keep", ""): ("takeout/keep/notes", True),
    ("Google Chat", "Groups"): ("takeout/chat/messages", False),
    ("Google Chat", "Users"): ("takeout/chat/users", False),
    ("Google Pay", "Google transactions"): ("takeout/pay/transactions", False),
    ("Google Pay", "Money sends and requests"): ("takeout/pay/money_sends", False),
    ("Access Log Activity", ""): ("takeout/access_log", False),
    ("Maps", "My labeled places"): ("takeout/maps/labeled_places", False),
    ("Maps", "Your local followed places"): ("takeout/maps/followed_places", False),
    ("Maps", "Commute routes"): ("takeout/maps/commute_routes", False),
    ("Maps (your places)", ""): ("takeout/maps/saved_places", False),
    ("Saved", ""): ("takeout/saved", False),
    ("Google Shopping", "Merchant Reviews"): ("takeout/shopping/merchant_reviews", False),
    ("Google Shopping", "Product Reviews"): ("takeout/shopping/product_reviews", False),
}


def takeout_place(name: str) -> tuple[str, str]:
    """(product, path under it) for a file in the export, else ("", "")."""
    parts = name.split("/")
    if len(parts) < 3 or not parts[0].lower().startswith("takeout"):
        return "", ""
    return parts[1], "/".join(parts[2:])


def takeout_target(name: str):
    """(endpoint, whole file) for a file of a product in TAKEOUT, else None."""
    product, under = takeout_place(name)
    return TAKEOUT.get((product, under.split("/")[0] if "/" in under else ""))


def _where(name: str) -> dict:
    parts = name.split("/")
    return {"_file": parts[-1], "_dir": parts[-2] if len(parts) > 1 else ""}


def takeout_items(name: str, data, endpoint: str, whole: bool):
    """(id, record, section) for one file of a TAKEOUT product. Every record
    carries the file it came from as _file and its folder as _dir: a Fit
    day's date, a Saved list's name and a Chat conversation are only there."""
    where = _where(name)
    if whole:
        yield f"{endpoint}:{where['_file']}", {**data, **where}, None
        return
    if isinstance(data, list):
        items = [(None, x) for x in data]
    elif isinstance(data, dict):
        lists = {k: v for k, v in data.items() if isinstance(v, list)}
        items = [(k, x) for k, v in lists.items() for x in v] or [(None, data)]
    else:
        return
    for section, item in items:
        if not isinstance(item, dict):
            item = {"value": item}
        record = {**item, **where}
        key = item.get("message_id") or rid(endpoint, section, record)
        yield key, record, section


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


def gmail_record(msg) -> dict:
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


def entries(root: Path, stack: contextlib.ExitStack) -> list:
    """(name, opener, size) for every file under root, inside zips too. The
    zips stay open until stack closes, so a file can be opened out of turn:
    a Keep note's image may be in another part of the export."""
    out = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path.suffix == ".zip":
            z = stack.enter_context(zipfile.ZipFile(path))
            for info in z.infolist():
                if not info.is_dir():
                    out.append((info.filename, lambda z=z, info=info: z.open(info), info.file_size))
        else:
            out.append((str(path.relative_to(root)), lambda path=path: open(path, "rb"), path.stat().st_size))
    return out


def _about(name: str) -> dict:
    return {"name": posixpath.basename(name), "mime_type": mimetypes.guess_type(name)[0]}


def pack(root: Path, out, files: Path | None = None) -> dict:
    counts: dict[str, int] = {}

    def write(endpoint, rid_, record, **extra):
        out.write(json.dumps({"endpoint": endpoint, "id": rid_, "record": record, **extra},
                             ensure_ascii=False) + "\n")
        counts[endpoint] = counts.get(endpoint, 0) + 1

    def save(kind, opener, size, endpoint, rid_, record):
        """A file of the export into the files folder, as <kind>/<n>."""
        if not size:
            return
        n = counts.get(f"files/{kind}", 0) + 1
        with opener() as fh:
            save_file(files, f"{kind}/{n}", fh, endpoint, rid_, record)
        counts[f"files/{kind}"] = n

    def keep_files(name, key, note):
        """The images and recordings a Keep note lists, each by its position."""
        for position, att in enumerate(note.get("attachments") or [], 1):
            path = posixpath.join(posixpath.dirname(name), att.get("filePath") or "")
            # Sometimes listed with another extension than the file has -
            # .jpg for a .jpeg - and then found by its stem.
            path = path if path in index else stems.get(posixpath.splitext(path)[0])
            if path is None:
                counts["files/missing"] = counts.get("files/missing", 0) + 1
                continue
            record = _about(path)
            record["mime_type"] = att.get("mimetype") or record["mime_type"]
            save("keep", *index[path], "google/keep", f"{key}/{position}", record)

    with contextlib.ExitStack() as stack:
        listing = entries(root, stack)
        index = {name: (opener, size) for name, opener, size in listing}
        stems = {posixpath.splitext(n)[0]: n for n in index
                 if takeout_place(n)[0] == "Keep" and not n.endswith((".json", ".html"))}
        for name, opener, size in listing:
            lower = name.lower()
            product, under = takeout_place(name)
            target = takeout_target(name)
            if product == "Drive":
                if files is not None:
                    save("drive", opener, size, "google/drive", under, _about(name))
            elif product == "Fit" and under.startswith("Activities/"):
                if files is not None:
                    stem = posixpath.splitext(posixpath.basename(name))[0]
                    session = f"{name.split('/')[0]}/Fit/All Sessions/{stem}.json"
                    key = f"takeout/fit/sessions:{stem}.json" if session in index else under
                    save("fit", opener, size, "google/fit", key, _about(name))
            elif target and lower.endswith(".csv"):
                endpoint, _ = target
                with opener() as fh:
                    rows = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", newline=""))
                    for row in rows:
                        data = {k: v for k, v in row.items() if k}
                        record = {**data, **_where(name)}
                        write(endpoint, rid(endpoint, None, record), record, file=Path(name).name)
            elif target and lower.endswith(".json"):
                endpoint, whole = target
                with opener() as fh:
                    try:
                        data = json.load(fh)
                    except ValueError:
                        counts["failed"] = counts.get("failed", 0) + 1
                        continue
                for key, record, section in takeout_items(name, data, endpoint, whole):
                    write(endpoint, key, record, file=Path(name).name, section=section)
                    if files is not None and endpoint == "takeout/keep/notes":
                        keep_files(name, key, record)
            elif lower.endswith(".mbox"):
                with opener() as fh:
                    for raw in mbox_messages(fh):
                        try:
                            msg = BytesParser(policy=policy.default).parsebytes(raw)
                            rec = gmail_record(msg)
                        except Exception as e:  # one bad message never stops the rest
                            counts["failed"] = counts.get("failed", 0) + 1
                            print(f"skipped a message in {Path(name).name}: {type(e).__name__}", file=sys.stderr)
                            continue
                        key = rec["message_id"] or "sha:" + hashlib.sha256(raw[:65536]).hexdigest()[:32]
                        write("gmail/takeout", key, rec, file=Path(name).name)
                        if files is not None:
                            folder = f"gmail/{counts['gmail/takeout']}"
                            if n := save_attachments(msg, files, folder, "google/gmail", key):
                                counts["files/gmail"] = counts.get("files/gmail", 0) + n
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
    parser = argparse.ArgumentParser(description="Pack a Google Takeout export; pipelines/google.md.")
    parser.add_argument("root", type=Path, help="the folder with Takeout's zips, or what they unpacked to")
    parser.add_argument("target", type=Path, help="the .jsonl.gz to write")
    parser.add_argument("--files", type=Path, metavar="DIR",
                        help="also write the export's files into DIR, for the NAS archive's inbox")
    args = parser.parse_args()
    root, target = args.root.expanduser(), args.target.expanduser()
    files = empty_folder(args.files.expanduser()) if args.files else None
    with gzip.open(target, "wt", encoding="utf-8") as out:
        counts = pack(root, out, files)
    print(f"{target}: {counts}, {target.stat().st_size / 1e6:.1f} MB")
    if files is not None:
        print(f"{files}: {folder_size(files) / 1e6:.1f} MB")
    if not any(k != "failed" for k in counts):
        sys.exit("nothing found - Gmail as mbox, My Activity as JSON or Chrome history in that folder?")


if __name__ == "__main__":
    main()
