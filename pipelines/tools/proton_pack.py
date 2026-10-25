#!/usr/bin/env python3
"""Pack a Proton Mail export into one file for the ingest_proton DAG.

    python3 pipelines/tools/proton_pack.py ~/proton-mail-export ~/proton.jsonl.gz --files ~/proton-files

The export is what Proton's own Mail Export tool writes: per account a
directory named after the address, holding mail_<timestamp>/ with one .eml
and one .metadata.json per message and a labels.json. This reads all of it
and writes one gzipped JSON line per message - the headers that matter, the
body as plain text, and each attachment's name, type and size. Never the
attachment itself: the packed file is text, not the export's gigabyte.

The attachments go to the NAS archive instead, with --files: each one
decoded into that folder as <n>/<position> - n a running number for the
message, position its place in the message's list from 1 - with a line in
the folder's files.jsonl, the manifest the archive's inbox keys it by:
endpoint proton, id <Proton message id>/<position> (pipelines/files.md).
Empty ones are left out.

Nothing is masked here. That happens in the DAG, the same as for every other
source (pipelines/dags/sensitive.py), so the output is as private as the
export it came from: keep it where the export is, and delete both once the
load is done; the files folder too, once it is in the inbox. Standard
library only; prints counts, never message contents. The whole procedure:
pipelines/proton.md.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from html.parser import HTMLParser
from pathlib import Path

# Proton's own folders and labels, which labels.json does not list.
SYSTEM_LABELS = {
    "0": "Inbox", "1": "All Drafts", "2": "All Sent", "3": "Trash", "4": "Spam",
    "5": "All Mail", "6": "Archive", "7": "Sent", "8": "Drafts", "9": "Outbox",
    "10": "Starred", "12": "Scheduled", "15": "Almost All Mail", "16": "Snoozed",
}
# The manifest in the --files folder (pipelines/dags/archive.py reads it).
MANIFEST = "files.jsonl"
# A body longer than this is cut, so one message stays well under Kafka's
# 8 MiB limit (clusters/lab/data/kafka.yaml) even in four-byte characters.
BODY_MAX = 1_000_000

_BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
          "blockquote", "pre", "table", "hr"}


class _Text(HTMLParser):
    """An HTML body as the text a reader sees: no tags, scripts or styles,
    a line break where a block ends."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in _BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    p.close()
    lines = (" ".join(line.split()) for line in "".join(p.out).splitlines())
    text, blank = [], False
    for line in lines:
        if line or not blank:
            text.append(line)
        blank = not line
    return "\n".join(text).strip()


def _content(part) -> str:
    try:
        return part.get_content()
    except (LookupError, ValueError, AssertionError):
        data = part.get_payload(decode=True) or b""
        return data.decode(part.get_content_charset() or "utf-8", errors="replace")


def body_text(msg) -> str:
    plain = msg.get_body(preferencelist=("plain",))
    if plain is not None:
        return _content(plain).strip()
    html = msg.get_body(preferencelist=("html",))
    if html is not None:
        return html_to_text(_content(html))
    return ""


def attachment_parts(msg) -> list:
    """The parts of a message that are attachments, in order: the n-th is
    position n in ods.proton_attachments, counted from 1."""
    out = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if not part.get_filename() and part.get_content_disposition() != "attachment":
            continue
        out.append(part)
    return out


def _about(part) -> dict:
    return {
        "name": part.get_filename() or "",
        "mime_type": part.get_content_type(),
        "inline": part.get_content_disposition() == "inline",
    }


def attachments(msg) -> list[dict]:
    return [{**_about(part), "size": len(part.get_payload(decode=True) or b"")}
            for part in attachment_parts(msg)]


def save_file(files: Path, file: str, data: bytes, endpoint: str, rid: str, record: dict) -> None:
    """A file into the --files folder at files/<file>, and its line in the
    manifest: the source and key ingest_files stores it under."""
    path = files / file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with open(files / MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps({"file": file, "endpoint": endpoint, "id": rid, "record": record},
                           ensure_ascii=False) + "\n")


def save_attachments(msg, files: Path, folder: str, endpoint: str, key: str) -> int:
    """Each of a message's attachments, decoded, to files/<folder>/<position>,
    with id <key>/<position>. Empty ones are skipped. The number saved."""
    saved = 0
    for position, part in enumerate(attachment_parts(msg), 1):
        data = part.get_payload(decode=True) or b""
        if data:
            save_file(files, f"{folder}/{position}", data, endpoint, f"{key}/{position}", _about(part))
            saved += 1
    return saved


def _people(value) -> list[dict]:
    return [{"name": n, "address": a.lower()} for n, a in getaddresses([str(value)]) if a]


def _meta_people(items) -> list[dict]:
    return [{"name": i.get("Name") or "", "address": (i.get("Address") or "").lower()}
            for i in items or [] if i.get("Address")]


def _msgids(value) -> list[str]:
    return [t.strip() for t in str(value or "").replace(">", "> ").split() if t.startswith("<")]


def message_record(account: str, meta: dict, msg, label_names: dict) -> dict:
    p = meta.get("Payload", meta)

    def people(header, meta_key):
        return _people(msg[header]) if msg[header] else _meta_people(p.get(meta_key))

    message_id = (_msgids(msg["Message-ID"]) or [p.get("ExternalID") or ""])[0]
    references = _msgids(msg["References"])
    in_reply_to = (_msgids(msg["In-Reply-To"]) or [""])[0]
    body = body_text(msg)
    label_ids = [str(i) for i in p.get("LabelIDs") or []]
    sender = p.get("Sender") or {}
    return {
        "id": p["ID"],
        "account": account,
        "message_id": message_id,
        # Proton's export has no conversation id: the thread is the first
        # message the References header names, as mail clients thread it.
        "thread_id": (references or [in_reply_to or message_id])[0],
        "in_reply_to": in_reply_to,
        "time": datetime.fromtimestamp(p.get("Time") or 0, timezone.utc).isoformat(),
        "subject": p.get("Subject") or str(msg["Subject"] or ""),
        "from": {"name": sender.get("Name") or "", "address": (sender.get("Address") or "").lower()},
        "to": people("To", "ToList"),
        "cc": people("Cc", "CCList"),
        "bcc": people("Bcc", "BCCList"),
        "reply_to": _meta_people(p.get("ReplyTos")) or _people(msg["Reply-To"] or ""),
        "label_ids": label_ids,
        "labels": [label_names.get(i, SYSTEM_LABELS.get(i, i)) for i in label_ids],
        "flags": p.get("Flags"),
        "unread": bool(p.get("Unread")),
        "replied": bool(p.get("IsReplied")),
        "replied_all": bool(p.get("IsRepliedAll")),
        "forwarded": bool(p.get("IsForwarded")),
        "size": p.get("Size"),
        "body_text": body[:BODY_MAX],
        "body_truncated": len(body) > BODY_MAX,
        "attachments": attachments(msg),
    }


def load_labels(path: Path) -> dict:
    """labels.json as id -> name, folders with their full path."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("Payload", data.get("Labels", list(data.values())))
    return {str(lb["ID"]): lb.get("Path") or lb.get("Name") or str(lb["ID"])
            for lb in data if isinstance(lb, dict) and "ID" in lb}


def pack(export: Path, out, files: Path | None = None) -> dict:
    counts = {"messages": 0, "failed": 0, "truncated": 0, "attachments": 0}
    if files is not None:
        counts["files"] = 0
    for account_dir in sorted(d for d in export.iterdir() if d.is_dir() and "@" in d.name):
        for mail_dir in sorted(account_dir.glob("mail_*")):
            labels = load_labels(mail_dir / "labels.json")
            for meta_path in sorted(mail_dir.glob("*.metadata.json")):
                eml_path = meta_path.with_name(meta_path.name.removesuffix(".metadata.json") + ".eml")
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    msg = BytesParser(policy=policy.default).parsebytes(eml_path.read_bytes())
                    rec = message_record(account_dir.name.lower(), meta, msg, labels)
                except Exception as e:  # one bad message never stops the rest
                    counts["failed"] += 1
                    print(f"skipped {meta_path.name}: {type(e).__name__}", file=sys.stderr)
                    continue
                out.write(json.dumps({"endpoint": "messages", "id": rec["id"], "record": rec},
                                     ensure_ascii=False) + "\n")
                counts["messages"] += 1
                counts["truncated"] += rec["body_truncated"]
                counts["attachments"] += len(rec["attachments"])
                if files is not None:
                    counts["files"] += save_attachments(msg, files, str(counts["messages"]), "proton", rec["id"])
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Pack a Proton Mail export; pipelines/proton.md.")
    parser.add_argument("export", type=Path, help="the directory Proton's Mail Export tool wrote")
    parser.add_argument("target", type=Path, help="the .jsonl.gz to write")
    parser.add_argument("--files", type=Path, metavar="DIR",
                        help="also write each attachment into DIR, for the NAS archive's inbox")
    args = parser.parse_args()
    export, target = args.export.expanduser(), args.target.expanduser()
    files = args.files.expanduser() if args.files else None
    if files is not None:
        files.mkdir(parents=True, exist_ok=True)
        if any(files.iterdir()):
            sys.exit(f"{files} is not empty - an earlier pack's files would go in with these")
    with gzip.open(target, "wt", encoding="utf-8") as out:
        counts = pack(export, out, files)
    print(f"{target}: {counts}, {target.stat().st_size / 1e6:.1f} MB")
    if files is not None:
        size = sum(p.stat().st_size for p in files.rglob("*") if p.is_file())
        print(f"{files}: {counts['files']} files, {size / 1e6:.1f} MB")
    if not counts["messages"]:
        sys.exit("no messages found - is that the directory the export tool wrote?")


if __name__ == "__main__":
    main()
