#!/usr/bin/env python3
"""Pack a VK ("ВКонтакте") data archive into one file for the ingest_vk DAG.

    python3 pipelines/tools/vk_pack.py "~/Downloads/VK Data.zip" ~/vk.jsonl.gz

The archive is what VK's "request your data" page gave until the account
was deleted: a zip of HTML pages in windows-1251, one folder per section.
This reads the zip as it is - no unpacking - and writes one gzipped JSON
line per record:

- vk/messages: every message - the conversation (its folder's id and the
  name VK showed), who wrote it (their profile link, or "you"), when, the
  text, whether it was edited, and attachments as VK described and linked
  them. VK's own message id is the key.
- vk/conversations: each conversation's id and name, from the archive's
  index of them.
- vk/audio: each track of the music list, "artist - title" and duration.
- vk/items: every entry of every other section - wall, comments, likes,
  bookmarks, profile, sessions, apps, ads, video, photos - as its text and
  links, with the section and page it came from.

Times are as the archive wrote them, in Russian ("12 янв 2019 в 10:00:00"),
in the time zone the account used; kept as text and read into a local
date-time. Nothing is masked here; the DAG does that. Standard library
only. Prints counts, never contents. The procedure: pipelines/vk.md.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path

MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6, "июл": 7,
          "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}
WHEN = re.compile(r"(\d{1,2})\s+([а-яё]+)\.?\s+(\d{4})\s+в\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", re.I)
VOID = {"br", "img", "meta", "link", "hr", "input", "wbr", "source"}
BLOCK = {"div", "br", "p", "li", "tr", "h1", "h2", "h3"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs), [], parent

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def find_all(self, cls: str):
        for c in self.children:
            if isinstance(c, Node):
                if cls in c.classes:
                    yield c
                yield from c.find_all(cls)

    def find(self, cls: str):
        return next(self.find_all(cls), None)

    def links(self) -> list[str]:
        out = [self.attrs["href"]] if self.tag == "a" and self.attrs.get("href") else []
        for c in self.children:
            if isinstance(c, Node):
                out += c.links()
        return out

    def text(self, skip: frozenset = frozenset()) -> str:
        parts: list[str] = []

        def walk(n):
            for c in n.children:
                if isinstance(c, str):
                    parts.append(c)
                elif not (c.classes & skip):
                    if c.tag in BLOCK:
                        parts.append("\n")
                    walk(c)
                    if c.tag in BLOCK:
                        parts.append("\n")
        walk(self)
        lines = [" ".join(line.split()) for line in "".join(parts).split("\n")]
        return "\n".join(line for line in lines if line).strip()


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def parse(raw: bytes) -> Node:
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:2000])
    tree = _Tree()
    tree.feed(raw.decode(m.group(1).decode() if m else "windows-1251", errors="replace"))
    tree.close()
    return tree.root


def when(text: str) -> str | None:
    """'12 янв 2019 в 10:00:00' -> '2019-01-12T10:00:00', local time."""
    m = WHEN.search(text)
    if not m:
        return None
    month = MONTHS.get(m.group(2).lower()[:3]) or MONTHS.get(m.group(2).lower())
    if not month:
        return None
    return (f"{int(m.group(3)):04d}-{month:02d}-{int(m.group(1)):02d}"
            f"T{int(m.group(4)):02d}:{m.group(5)}:{m.group(6) or '00'}")


def crumbs(root: Node) -> list[str]:
    return [c.text() for c in root.find_all("ui_crumb")]


def attachments(node: Node) -> list[dict]:
    out = []
    for a in node.find_all("attachment"):
        desc = a.find("attachment__description")
        out.append({"description": desc.text() if desc else a.text(), "links": a.links()})
    return out


def messages(root: Node, conversation: str, name: str):
    for m in root.find_all("message"):
        header = m.find("message__header")
        head = header.text() if header else ""
        sender_links = header.links() if header else []
        outgoing = head.startswith("Вы,") or head.startswith("You,")
        rest = m.text(skip=frozenset({"message__header", "kludges"}))
        kludges = m.find("kludges")
        yield {
            "id": m.attrs.get("data-id") or "",
            "conversation_id": conversation,
            "conversation_name": name,
            "outgoing": outgoing,
            "sender_name": "" if outgoing else head.rsplit(",", 1)[0].strip(),
            "sender_link": sender_links[0] if sender_links else "",
            "time_text": head.rsplit(",", 1)[-1].strip() if "," in head else "",
            "time": when(head),
            "edited": "(ред.)" in head or "(edited)" in head,
            "text": rest,
            "attachments": attachments(kludges) if kludges else [],
        }


def pack(archive: Path, out) -> dict:
    counts: dict[str, int] = {}

    def write(endpoint, rid, record):
        out.write(json.dumps({"endpoint": endpoint, "id": rid, "record": record}, ensure_ascii=False) + "\n")
        counts[endpoint] = counts.get(endpoint, 0) + 1

    with zipfile.ZipFile(archive) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith((".html", ".htm")))
        # Conversation names, from the index page of the messages section.
        conv_names: dict[str, str] = {}
        for n in names:
            if n.split("/")[-2:-1] == ["messages"] and "index" in n.split("/")[-1]:
                for a in parse(z.read(n)).find_all("item"):
                    for href in a.links():
                        cid = href.split("/")[0]
                        if cid.lstrip("-").isdigit():
                            conv_names[cid] = a.text()
        for cid, name in conv_names.items():
            write("vk/conversations", cid, {"id": cid, "name": name})

        for n in names:
            parts = n.split("/")
            section = parts[1] if len(parts) > 2 else ""
            page = "/".join(parts[1:])
            if not section:
                continue
            try:
                root = parse(z.read(n))
            except Exception as e:  # one bad page never stops the rest
                counts["failed"] = counts.get("failed", 0) + 1
                print(f"skipped {page}: {type(e).__name__}", file=sys.stderr)
                continue
            if section == "messages" and len(parts) >= 4:
                cid = parts[2]
                name = conv_names.get(cid) or (crumbs(root)[-1] if crumbs(root) else "")
                for rec in messages(root, cid, name):
                    rid = rec["id"] or hashlib.sha256(json.dumps(rec, ensure_ascii=False).encode()).hexdigest()[:32]
                    write("vk/messages", f"{cid}/{rid}", rec)
            elif section == "messages":
                continue  # the index, read above
            elif section == "audio":
                for item in root.find_all("audio"):
                    title, duration = item.find("audio__title"), item.find("audio__duration")
                    rec = {"title": title.text() if title else item.text(),
                           "duration": duration.text() if duration else "",
                           "album": " / ".join(crumbs(root)[1:]), "page": page}
                    write("vk/audio", hashlib.sha256(json.dumps(rec, ensure_ascii=False).encode()).hexdigest()[:32], rec)
            else:
                for i, item in enumerate(root.find_all("item")):
                    rec = {"section": section, "page": page, "position": i,
                           "text": item.text(skip=frozenset({"kludges"})),
                           "time": when(item.text()),
                           "links": item.links(),
                           "attachments": attachments(item)}
                    write("vk/items", hashlib.sha256(json.dumps(rec, ensure_ascii=False).encode()).hexdigest()[:32], rec)
    return counts


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("usage: vk_pack.py <VK archive .zip> <output .jsonl.gz>")
    archive, target = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    with gzip.open(target, "wt", encoding="utf-8") as out:
        counts = pack(archive, out)
    print(f"{target}: {counts}, {target.stat().st_size / 1e6:.1f} MB")
    if not counts.get("vk/messages"):
        sys.exit("no messages found - is that VK's data archive?")


if __name__ == "__main__":
    main()
