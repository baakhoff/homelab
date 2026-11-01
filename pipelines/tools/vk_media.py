#!/usr/bin/env python3
"""Fetch the photos still reachable from a VK data archive, for Immich.

    python3 pipelines/tools/vk_media.py survey "~/Downloads/VK Data.zip"
    python3 pipelines/tools/vk_media.py fetch "~/Downloads/VK Data.zip" ~/vk-media

The archive (pipelines/vk.md) never held the files: every photo and video
in it is a link to VK's servers, and the account was deleted in 2020, so
most of them no longer answer. This reads the same zip as vk_pack.py,
through its parser, and collects every photo link - messages'
attachments, and the wall, photo and other sections' entries.

- survey: how many photo and video links there are, by year, and how many
  of a sample of the photos still answer. Nothing is saved.
- fetch: downloads every photo that still answers into a folder, named
  VK_<date>_<time>_<hash>.jpg and dated by its message or entry, so Immich
  places it in its own day - VK stripped the photos' own dates. Run it
  again and it skips what it already has. Then upload the folder with
  immich-go (pipelines/vk.md).

Videos are counted, not fetched: their links are VK's player pages, not
files. Standard library only. Prints counts, never names or contents.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vk_pack import attachments, messages, parse, when  # noqa: E402

IMAGE = re.compile(r"\.(jpe?g|png|gif|webp)(\?|$)", re.I)
PHOTO_WORDS = ("фотограф", "photo")
VIDEO_WORDS = ("видео", "video")
AGENT = "Mozilla/5.0 (X11; Linux x86_64) vk_media"


def kind(description: str, link: str) -> str | None:
    d = description.strip().lower()
    if d.startswith(VIDEO_WORDS):
        return "video"
    if link.startswith("http") and (d.startswith(PHOTO_WORDS) or IMAGE.search(link)):
        return "photo"  # a link to VK's photo page, not the file, simply fails to fetch
    return None


def collect(archive: Path) -> dict[str, dict]:
    """Every photo and video link, once each: {url: {"kind", "time"}}, the
    earliest time it was seen at."""
    found: dict[str, dict] = {}

    def add(k, url, t):
        if not k:
            return
        seen = found.get(url)
        if seen is None or (t and (not seen["time"] or t < seen["time"])):
            found[url] = {"kind": k, "time": t}

    with zipfile.ZipFile(archive) as z:
        for n in sorted(z.namelist()):
            parts = n.split("/")
            if not n.lower().endswith((".html", ".htm")) or len(parts) < 3:
                continue
            section = parts[1]
            try:
                root = parse(z.read(n))
            except Exception:
                continue
            if section == "messages":
                if len(parts) < 4:
                    continue
                for m in messages(root, parts[2], ""):
                    for a in m["attachments"]:
                        for link in a["links"]:
                            add(kind(a["description"], link), link, m["time"])
            elif section != "audio":
                for item in root.find_all("item"):
                    t = when(item.text())
                    for a in attachments(item):
                        for link in a["links"]:
                            add(kind(a["description"], link), link, t)
                    for link in item.links():
                        if IMAGE.search(link):
                            add("photo", link, t)
    return found


def name_for(url: str, t: str | None) -> str:
    h = hashlib.sha256(url.encode()).hexdigest()[:12]
    stamp = t.replace("-", "").replace(":", "").replace("T", "_") if t else "00000000_000000"
    ext = (IMAGE.search(url).group(1).lower() if IMAGE.search(url) else "jpg").replace("jpeg", "jpg")
    return f"VK_{stamp}_{h}.{ext}"


def get(url: str, timeout: float = 20) -> bytes | None:
    """The image, or None when the link no longer gives one."""
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if not r.headers.get("Content-Type", "").startswith("image/"):
                return None
            body = r.read()
            return body if len(body) > 1024 else None  # VK's "deleted" stubs are tiny
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, OSError):
        return None


def survey(archive: Path, sample: int = 60) -> None:
    found = collect(archive)
    photos = sorted(u for u, v in found.items() if v["kind"] == "photo")
    videos = [u for u, v in found.items() if v["kind"] == "video"]
    years: dict[str, int] = {}
    for u in photos:
        y = (found[u]["time"] or "????")[:4]
        years[y] = years.get(y, 0) + 1
    print(f"photo links: {len(photos)}, video links: {len(videos)} (not fetched)")
    print("photos by year: " + ", ".join(f"{y}: {c}" for y, c in sorted(years.items())))
    if not photos:
        return
    step = max(1, len(photos) // sample)
    picked = photos[::step][:sample]
    with ThreadPoolExecutor(4) as pool:
        alive = sum(1 for b in pool.map(get, picked) if b)
    print(f"sample: {alive} of {len(picked)} still answer"
          f" - about {round(len(photos) * alive / len(picked))} photos to fetch")


def fetch(archive: Path, folder: Path, workers: int = 4) -> None:
    found = collect(archive)
    photos = sorted(u for u, v in found.items() if v["kind"] == "photo")
    folder.mkdir(parents=True, exist_ok=True)
    todo = [u for u in photos if not (folder / name_for(u, found[u]["time"])).exists()]
    print(f"photo links: {len(photos)}, already here: {len(photos) - len(todo)}, to try: {len(todo)}")
    counts = {"saved": 0, "gone": 0}

    def one(url):
        body = get(url)
        if not body:
            return False
        t = found[url]["time"]
        path = folder / name_for(url, t)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(body)
        if t:
            ts = time.mktime(datetime.fromisoformat(t).timetuple())
            os.utime(tmp, (ts, ts))
        tmp.rename(path)
        return True

    with ThreadPoolExecutor(workers) as pool:
        for i, ok in enumerate(pool.map(one, todo), 1):
            counts["saved" if ok else "gone"] += 1
            if i % 500 == 0:
                print(f"  {i}/{len(todo)}: {counts}")
    print(f"done: {counts}, in {folder}")


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "survey":
        survey(Path(args[1]).expanduser())
    elif len(args) == 3 and args[0] == "fetch":
        fetch(Path(args[1]).expanduser(), Path(args[2]).expanduser())
    else:
        sys.exit("usage: vk_media.py survey <VK archive .zip>\n"
                 "       vk_media.py fetch <VK archive .zip> <folder>")


if __name__ == "__main__":
    main()
